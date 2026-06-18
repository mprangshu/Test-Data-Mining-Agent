# ARCHITECTURE.md — Nodes, topology & state

> Companion to [`CONTEXT.md`](CONTEXT.md). Visual: [`architecture.svg`](architecture.svg). This doc
> explains the LangGraph topology, every node (what it reads/writes), and the shared state.

---

## Topology

```
START → parse → load_results → mongo_lookup → vector_search → coverage_gap
      → generate → review (HITL, interrupt) → synthesise → persist → END
```

Single-parent sequential chain (not parallel). Reasons: a staggered multi-parent fan-in into
`generate` re-ran upstream nodes when `review` interrupts on resume; sequential keeps
interrupt/resume clean and the data volumes make the cost negligible. Defined in `graph.py`;
checkpointer is `MemorySaver`. Nodes are wired as bare functions, so the graph runs deterministic
(`llm=None`) — the Gemini seam exists but is a separate toggle.

**Node colours (see SVG):** teal = deterministic · purple = vector (ChromaDB) · coral = LLM seam ·
amber = human-in-the-loop · green = output/loop.

---

## Shared state (`state.py` · `AgentState`)

A single `TypedDict` flows through the graph; each node returns only the keys it updates.
`gaps`/`errors` use `operator.add` reducers so notes accumulate without clobbering.

| Field | Type | Written by |
|---|---|---|
| `input_path` | str | caller |
| `parsed_fields` | `list[ParsedField]` | parse |
| `input_rows` / `input_columns` / `input_row_count` | rows · cols · int | parse |
| `result_signals` | `list[ResultSignal]` | load_results |
| `seed_values` | `list[SeedValue]` | load_results |
| `existing_data` | `list[ExistingRecord]` (fields + row-aligned `rows`) | mongo_lookup |
| `retrieved_data` | `list[RetrievedRecord]` (fields + `rows` + similarity) | vector_search |
| `coverage_gaps` | `list[CoverageGap]` | coverage_gap |
| `candidate_sets` | `list[FieldCandidates]` | generate |
| `review_selections` | `list[ReviewSelection]` | review (HITL) |
| `final_dataset` | `list[dict]` (clean, for CSV) | synthesise |
| `output_rows` | `list[OutputRow]` (fields + source + row_uid) | synthesise |
| `report` | dict | synthesise |
| `round_index` / `seed_selection` | int · rows | iterative loop (`/generate-more`) |
| `persist_decision` / `persist_label` / `persist_tags` / `persist_receipt` | gate inputs/result | /persist |
| `gaps` / `errors` | `list[str]` (reducers) | any node |

Key dataclasses: `ParsedField`, `ResultSignal`, `SeedValue`, `ExistingRecord`, `RetrievedRecord`,
`CoverageGap`, `CandidateSet`, `FieldCandidates`, `ReviewSelection`, `OutputRow`.

---

## Node reference

### `parse` — deterministic — `nodes/parse.py`
Reads the **primary** inputs (`test_cases/` or the input dir). Tabular files (csv/xlsx/json) →
headers are field names (scenario/id columns excluded); `.txt` → Gherkin `<placeholders>`. Infers a
category + constraints per field. Also captures the **original rows verbatim** via `_select_primary`
(most-rows table wins; merges files with identical headers) → `input_rows`, `input_columns`,
`input_row_count`. Never crashes → `gaps`.
**Writes:** `parsed_fields`, `input_rows`, `input_columns`, `input_row_count`, `gaps`.

### `load_results` — deterministic — `nodes/load_results.py`
Parses **supporting** results: JUnit `<property name=… value=…>` and Playwright `annotations`.
Produces `result_signals` (tag, scenario type, outcome, fields exercised) and `seed_values` (real
values from **passing** runs only). No results dir → empty + an "unseeded" gap note.
**Writes:** `result_signals`, `seed_values`, `gaps`.

### `mongo_lookup` — deterministic, READ-ONLY — `nodes/mongo_lookup.py`
Matches stored datasets to the parsed fields (field-name overlap or test-case id). Live via
`MONGODB_URI`, else local JSON in `data/sample_mongo/` (`MONGO_LOCAL_DIR`). Each record carries
column pools (`fields`) **and** row-aligned `rows` (coherent reuse + provenance). Unreachable/empty →
`[]` + gap.
**Writes:** `existing_data` (the **fetched** source), `gaps`.

### `vector_search` — vector (ChromaDB), READ-ONLY — `nodes/vector_search.py`
Embeds a descriptive query (field names + categories) with the active embedder and queries the
collection (cosine, top-K=5, threshold 0.40 for MiniLM via `CHROMA_THRESHOLD`). Reads back `fields`
and row-aligned `rows` from metadata. Missing store → `[]` + gap.
**Writes:** `retrieved_data` (the **gathered** source), `gaps`.

### `coverage_gap` — deterministic — `nodes/coverage_gap.py`
Builds the matrix `required fields × {valid, boundary, negative, edge}` minus what `result_signals`
exercised (a ran-but-failed scenario still counts as exercised). With no results, every cell is a
gap.
**Writes:** `coverage_gaps`.

### `generate` — LLM seam (deterministic default) — `nodes/generate.py`
Per field, builds candidate value **sets** for the HITL gate: `gen_A` (valid-leaning, seeded from
real passing values, constraint-validated), `gen_B` (gap-filling: boundary/negative/edge), plus
pass-through `existing`/`retrieved` sets. Anti-hallucination: every valid value satisfies the
field's constraints. Placeholder guard rejects `sample_value_*` / `generated_\d+` / `test_*`. For
unknown schemas, `_synth` produces plausible values from constraints (no hardcoded column tables on
the primary path).
**Writes:** `candidate_sets`.

### `review` — human-in-the-loop, ALWAYS — `nodes/review.py`
`interrupt(build_payload(...))` pauses the graph and surfaces each field's sets. Resuming with
`Command(resume={"review_selections":[...]})` records the analyst's pick per field (or exclusion, or
custom values). `auto_selections()` (widest coverage) drives non-UI resumes/tests.
**Writes:** `review_selections`.

### `synthesise` — deterministic + LLM seam — `nodes/synthesise.py`
The assembler. Output = **`input_rows` (verbatim) + generated + fetched + gathered**.
- Generated rows are coherent whole records — LLM-grounded (`_llm_rows`) or offline clone-and-perturb
  (`_perturb`), grounded on originals + analyst picks + fetched + gathered (observed value pools).
- Uses `inference.profile_columns` + `IdMinter` (unique ids) + learned `correlated_pairs`.
- Scenario mix always includes valid; `scenario_tag`/`data_category` written only if present, tag =
  content. Row count relaxed: `n_new = max(input_n, 5)`, guard `output ≥ input`.
- Emits `final_dataset` (clean, fields only) and `output_rows` (with `source` + `row_uid`).
**Writes:** `final_dataset`, `output_rows`, `report`.

### `persist` — deterministic, GATED — `nodes/persist.py`
Only writes when the save gate is set. `write_dataset()` writes the dataset (column pools + row-
aligned `rows`) to MongoDB (`MONGODB_URI`) or the local seed (closing the reuse loop) and **upserts**
ChromaDB so it's retrievable next run. No Neo4j, no `KG_SIGNAL_*`.
**Writes:** `persist_receipt`, `gaps` (only on a save).

---

## The two stores + embeddings

| Store | Holds | Why |
|---|---|---|
| **MongoDB** | datasets as documents (column pools + row-aligned rows) | document shape fits; the "fetched" source |
| **ChromaDB** | dataset embeddings (384-dim, cosine) | vector similarity = the "gathered" source |

Neither is a graph database (invariant #2). Embeddings: `all-MiniLM-L6-v2` offline via
`embedding.py`, deterministic hashed fallback when unavailable. See [`CONTEXT.md` §5](CONTEXT.md).

---

## Autonomy

L2 only. The set-selection review gate **always** runs (no L1/L3 skip path). The only other human
decision is the explicit save gate in `persist`. There is no `AutonomyLevel` enum.
