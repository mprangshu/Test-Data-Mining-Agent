# CONTEXT-v3.md — Provenance, Iterative Generation & Real Embeddings

> **For Claude Code.** This builds on `IMPROVEMENT.md` + `IMPROVEMENT-2.md` (both still apply:
> additive, schema-agnostic, coherent, output > input). This doc adds four senior-confirmed
> changes and a phase plan. Frontend changes are required.
>
> **Hard invariants that DO NOT change:** read-only until the persist gate; MongoDB + ChromaDB,
> no Neo4j; deterministic-before-LLM; graceful degradation; never hardcode column names or
> per-domain coherence rules (the schema is learned from the uploaded data).

---

## 1. The four changes (what's new)

1. **Grounded generation (senior's method).** Generated rows are produced by mapping the
   **user input** (test case / user story / "get data" request) against the **fetched** data
   (MongoDB) and **gathered** data (ChromaDB). Fetched + gathered are the *reference material*
   the LLM grounds on; the input says *what* to make. Generated = LLM, Fetched = MongoDB,
   Gathered = ChromaDB.

2. **Provenance, UI-only.** Every output row carries a **source** = `generated | fetched |
   gathered`. The **UI** shows this (colour/label per row). The **downloaded CSV does NOT contain
   it** — the file is clean test data with the original columns only. Provenance is metadata
   that rides alongside the rows in the API/UI, never a column in the sheet.

3. **Iterative generation loop.** In the UI the QA engineer **selects rows they like** (across
   all three sources). Those selected rows become the **seed/input for the next generation
   round**: generate -> user picks good rows -> those seed the next batch -> repeat. Each round
   grounds on the user's curated selection plus fetched/gathered data.

4. **Real embeddings — `all-MiniLM-L6-v2` (local).** Replace the deterministic hashed embedder
   with the locally-available `all-MiniLM-L6-v2` sentence-transformer in all three places that
   embed. Raise the ChromaDB similarity threshold accordingly.

**Row-count rule (relaxed, per senior):** *No hard bound.* Aim for **>= the number of original
rows** (more is fine). It must not be "too few." Drop the strict EXPANSION_FACTOR assertion;
keep a soft target (default: at least `input_rows` new rows, i.e. output ~2x) and never fail a
run for producing "too many."

---

## 2. Grounded generation — the mechanism (schema-agnostic)

```
            user input (test case / user story / data request)
                              |
        +---------------------+---------------------+
        v                                           v
  Fetched (MongoDB)                          Gathered (ChromaDB)
  existing records                           similar records
        +---------------------+---------------------+
                              v
        LLM: "map input -> reference data -> generate NEW coherent rows"
                              v
              Generated rows (grounded, source="generated")
```

The generation prompt receives: the exact columns, the user input, and a sample of fetched +
gathered rows as **examples to infer types/relationships from** (never hardcoded). See
`IMPROVEMENT-2.md §1` for the prompt shape and the offline clone-and-perturb fallback.

**When fetched/gathered are empty** (fresh MongoDB / no similar cases): generation still proceeds
from the **user input alone** (pure LLM, or deterministic fallback offline). Empty stores reduce
grounding; they never block generation.

---

## 3. State / data-model changes

Each output row becomes a record with provenance kept **separate from the data fields**:

```python
@dataclass
class OutputRow:
    fields: dict[str, Any]                 # ONLY the uploaded columns -> values (the CSV content)
    source: Literal["generated", "fetched", "gathered"]   # UI metadata, NOT a CSV column
    # optional: a stable row uid so the UI can reference selections back to the agent
    row_uid: str

class AgentState(TypedDict, total=False):
    ...
    output_rows: list[OutputRow]           # replaces/augments final_dataset
    seed_selection: list[dict]             # rows the user picked to seed the NEXT round
    round_index: int                       # which iteration we're on
```

- `final_dataset` for CSV export = `[r.fields for r in output_rows]` (originals + new), **no
  source key**.
- The API returns `output_rows` *with* `source` for the UI.
- Originals (the uploaded rows) are included with `source="fetched"`? **No** — originals are the
  user's own input; tag them `source="input"` OR simply include them untagged as the base set and
  only tag the NEW rows by their three sources. (Pick one; recommended: originals carry
  `source="input"` so the UI can show "your data" vs the three generated sources. Confirm with
  senior if unsure — see Open Questions.)

---

## 4. Real embeddings — `all-MiniLM-L6-v2`

The model is available locally. Replace `DeterministicEmbeddingFunction` in the three embed sites:
`vector_search.py`, `persist.py`, `generate_fixtures.py`.

```python
# embedding.py — swap the deterministic embedder for a local sentence-transformer
from sentence_transformers import SentenceTransformer
import os

_MODEL_PATH = os.environ.get("EMBED_MODEL_PATH", "all-MiniLM-L6-v2")  # local path or name
_model = None

def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_PATH)   # loads from local cache/path
    return _model

def embed(text: str) -> list[float]:
    return _get_model().encode(text, normalize_embeddings=True).tolist()

# ChromaDB embedding function wrapper
from chromadb import EmbeddingFunction
class LocalMiniLMEmbeddingFunction(EmbeddingFunction):
    def __call__(self, input: list[str]) -> list[list[float]]:
        return _get_model().encode(input, normalize_embeddings=True).tolist()
```

Then:
- Replace `DeterministicEmbeddingFunction()` -> `LocalMiniLMEmbeddingFunction()` everywhere.
- **Re-seed ChromaDB** (`generate_fixtures.py`) so the stored vectors use the new model — old
  vectors from the hashed embedder are incompatible and must be regenerated.
- **Raise the threshold:** `all-MiniLM-L6-v2` gives real cosine scores, so set
  `CHROMA_THRESHOLD` default to ~`0.70` (was `0.40` for the hashed embedder). Tune on real data.
- `all-MiniLM-L6-v2` outputs **384-dim** vectors; ensure no dimension is hardcoded elsewhere.
- Dependency: add `sentence-transformers` to `requirements.txt`. It must run offline using the
  locally-available model (no download) — point `EMBED_MODEL_PATH` at the local folder.

---

## 5. Phase plan

Each phase is independently testable. Backend phases first so the frontend has real data shapes
to build against.

### Phase 1 — Embeddings swap (backend, isolated)
- [ ] Add `sentence-transformers`; implement `LocalMiniLMEmbeddingFunction` + `embed()` (section 4).
- [ ] Replace the deterministic embedder in `vector_search.py`, `persist.py`, `generate_fixtures.py`.
- [ ] Re-seed ChromaDB with the new model; raise `CHROMA_THRESHOLD` to ~0.70.
- [ ] Verify offline load from the local model path (no network).
- **Done when:** `vector_search` returns sensible similar cases on real data; similar test cases
  score higher than unrelated ones.

### Phase 2 — Grounded generation (backend)
- [ ] `generate`/`synthesise`: build NEW rows by mapping **user input + fetched + gathered** via
      the LLM (section 2), schema-agnostic, coherent (apply `IMPROVEMENT-2.md §1`).
- [ ] Tag each NEW row with `source` (`generated`/`fetched`/`gathered`). A row taken straight from
      MongoDB = `fetched`; from ChromaDB = `gathered`; LLM-made = `generated`.
- [ ] Relax row count: soft target `>= input_rows` new rows; remove the hard EXPANSION assertion;
      never fail for "too many".
- [ ] Mint unique ids for id-like columns; keep mostly-empty columns mostly empty (per `IMPROVEMENT-2`).
- **Done when:** output is coherent, grounded, source-tagged; originals preserved; count not "too few".

### Phase 3 — Provenance in API, clean CSV (backend)
- [ ] State: add `OutputRow` (fields + source + row_uid), `output_rows`, `round_index`,
      `seed_selection` (section 3).
- [ ] `/mine` (or `/resume`) returns `output_rows` WITH `source` for the UI.
- [ ] CSV export = fields only, original columns, **no source column**. Provide a
      `GET /export` or client-side blob that strips provenance.
- **Done when:** API response carries per-row source; exported CSV is clean (no source/no extra cols).

### Phase 4 — Iterative loop (backend)
- [ ] New endpoint `POST /generate-more` (or extend `/resume`): accepts `seed_selection`
      (the rows the user picked) + original input; runs another grounded round using the
      selection as the seed/reference; increments `round_index`.
- [ ] Each round appends to the working set; the user can iterate N times.
- **Done when:** selecting rows + "generate more" produces a new grounded batch seeded by the
      selection.

### Phase 5 — Frontend: provenance display (UI)
- [ ] Render the result table from `output_rows`, **colour/label each row by `source`**
      (Generated / Fetched / Gathered, plus the user's input rows). Legend + filter by source.
- [ ] Keep the table read-only here; selection comes in Phase 6.
- **Done when:** every row visibly shows its origin; user can tell the three apart at a glance.

### Phase 6 — Frontend: selection + iterate (UI)
- [ ] Per-row checkbox (and select-all-by-source). Selected rows -> `seed_selection`.
- [ ] "Generate more from selected" button -> `POST /generate-more`; show the new round appended
      (or as a new wave) with its own source tags.
- [ ] Round indicator (Round 1, 2, ...). Allow repeating.
- **Done when:** generate -> pick rows -> generate-more loops smoothly in the UI.

### Phase 7 — Frontend: clean download (UI)
- [ ] "Download CSV" exports fields only — original columns, **no source column** — for the
      whole current working set (originals + all kept generated/fetched/gathered rows).
- [ ] (Optional) "Download with sources" as a separate debug export, clearly secondary.
- **Done when:** downloaded sheet is clean test data; provenance exists only on screen.

### Phase 8 — Tests & universality
- [ ] Re-run on subscription data AND a **second, different-schema** CSV (loans/sensors) — assert
      coherent, grounded, source-tagged, clean CSV, no domain hardcoding (`IMPROVEMENT-2 §6`).
- [ ] Assert: CSV has no `source`/`data_category` column; API has per-row source; iterate loop works;
      embeddings load offline.

---

## 6. Acceptance criteria (end state)

| Check | Pass condition |
|---|---|
| Grounded | generated rows reflect user input + fetched + gathered (not invented blind) |
| Provenance (UI) | every row shows source = generated/fetched/gathered (+ input) on screen |
| Clean CSV | downloaded file = original columns only; no `source`, no `data_category` |
| Iterative | user selects rows -> "generate more" -> new grounded round seeded by selection |
| Row count | output >= input rows (more is fine); never "too few"; no hard cap |
| Real embeddings | `all-MiniLM-L6-v2` used at all 3 embed sites, offline; threshold ~0.70; Chroma re-seeded |
| Still additive | originals preserved; coherent; schema-agnostic; read-only until persist |

---

## 7. Open questions to confirm with senior

1. Should the **original uploaded rows** appear in the result table tagged `input` (recommended),
   or be hidden so only the three generated sources show?
2. On "generate more," do new rows **append** to the current set, or **replace** it (start fresh
   from the selection)? (Recommended: append, with a round marker.)
3. Final CSV: include the **kept fetched/gathered rows** too, or **only generated**? (Senior said
   the sheet is "all data" -> include all kept rows.)
4. Confirm the local `all-MiniLM-L6-v2` path/folder so `EMBED_MODEL_PATH` can point at it.

---

## 8. One-paragraph brief for Claude Code

> Add four things on top of the existing additive, schema-agnostic, coherent generator. (1) Ground
> generation in the senior's method: the LLM maps the user input (test case / user story / data
> request) against fetched data (MongoDB) and gathered data (ChromaDB) to produce new coherent
> rows — fetched/gathered are the reference examples, never hardcoded rules; empty stores fall back
> to input-only generation. (2) Tag every row with a source — generated (LLM), fetched (MongoDB),
> gathered (ChromaDB) — shown in the UI only; the downloaded CSV is clean (original columns, no
> source/no data_category). (3) Add an iterative loop: the user selects rows in the UI, those become
> the seed for another grounded generation round (generate -> pick -> generate-more -> repeat). (4)
> Swap the deterministic embedder for the locally-available all-MiniLM-L6-v2 (sentence-transformers,
> offline, 384-dim) in vector_search.py, persist.py, generate_fixtures.py; re-seed ChromaDB and
> raise the similarity threshold to ~0.70. Relax the row count: aim for >= input rows (more is fine),
> no hard cap, never fail for too many; just don't produce too few. Do it in phases — backend
> (embeddings, grounded generation, provenance API, iterate endpoint) then frontend (per-row source
> display, selection + generate-more, clean download) — and prove universality on a second schema.
> Keep all invariants: read-only until persist, Mongo+Chroma only (no Neo4j), deterministic-before-LLM,
> originals preserved, no hardcoded column names.
