# BUILD-PLAN.md — v2 (test-data generation pivot)

> **What this is:** the phased TODO to build the **v2 agent** described in
> [`TDM-PIVOT-v2.md`](TDM-PIVOT-v2.md): test cases/stories + result files → mine MongoDB/ChromaDB
> → detect coverage gaps → generate candidate value SETS → set-based HITL → CSV → optional save-back.
>
> **Guiding principle — vertical slices.** Each phase ends in something runnable/demoable. We get a
> thin upload → mine → generate → CSV path working (deterministic) before enriching with the
> set-based HITL gate and the save-back loop.
>
> 🔒 **Invariants (pivot §11):** read-before-write on MongoDB (only write at the persist gate) ·
> no Neo4j/graph DB · deterministic-before-LLM · graceful degradation · LLM via Hub router seam ·
> anti-hallucination (constraint-valid values). See [`CLAUDE.md`](../CLAUDE.md).

## Legend
- [ ] to do · [x] done · 🔒 invariant checkpoint · 🎯 demoable milestone

> **v1 status (retired):** the original analysis agent (flaky/clustering/quality report + full
> demo UI) was built and verified — see git history and the completed checklist in
> [`ROADMAP.md`](ROADMAP.md). v2 reuses its plumbing (interrupt/resume, NDJSON streaming, offline
> Chroma embedder, gaps/errors reducers) but replaces the nodes, schema, API surface, and UI.

## Status at a glance

| Phase | Outcome | Depends on |
|---|---|---|
| 0 | ✅ Teardown + new `state.py` + deps; green (empty) baseline | — |
| 1 | ✅ Inputs parsed: `parse` (test cases) + `load_results` (results → signals + seeds) | 0 |
| 2 | ✅ Sample data + stores: `generate_fixtures` seeds Mongo/Chroma/inputs; `mongo_lookup` + `vector_search` | 1 |
| 3 | ✅ Gaps + generation: `coverage_gap` + `generate` (2–3 constraint-valid sets/field) | 2 |
| 4 | ✅ Graph wired + backend `/mine` + `/resume`; pipeline runs to review interrupt; resume → `final_dataset` 🎯 | 3 |
| 5 | ✅ Frontend: two-bucket upload → mine → trace to the review gate | 4 |
| 6 | ✅ Set-based HITL: `review` interrupt + `ReviewGate` radios + `/resume` → CSV report + download 🎯 | 5 |
| 7 | ✅ Save-back loop: `persist` (Mongo+Chroma) + `PersistGate`; re-run reuses saved data 🎯 | 6 |
| 8 | ✅ Tests (unit/integration/adversarial) + polish + demo dry-run 🎯 | all |
| 9 | ✅ **Additive + schema-agnostic output fix** ([`IMPROVEMENT.md`](IMPROVEMENT.md)): output = originals + new rows, always larger, any schema, LLM-coherent 🎯 | 8 |

---

## Phase 0 — Teardown & new contract
*Goal: clear v1's analysis nodes, lay down the v2 state schema, keep the repo importable/green.*

- [x] Deleted v1 files (pivot §6): `nodes/flaky_detect.py`, `nodes/failure_clustering.py`,
      `nodes/synthesis.py`, `nodes/stubs.py`, `scripts/score_golden.py`, and the v1 tests
      (`test_flaky_detect`, `test_validate`, `test_synthesis_persist`, `test_failure_clustering`,
      plus `test_backend`/`test_integration`/`test_adversarial` — they import deleted modules and
      are rewritten for the new pipeline later). Kept `data/sample_upload/*` (reshaped in Phase 2).
- [x] Rewrote `src/test_data_mining/state.py` to the v2 schema (pivot §4) — `ParsedField`,
      `ResultSignal`, `SeedValue`, `ExistingRecord`, `RetrievedRecord`, `CoverageGap`,
      `CandidateSet`, `FieldCandidates`, `ReviewSelection`, new `AgentState`; `gaps`/`errors`
      accumulate-reducers kept; added `initial_state(input_path, autonomy_level=L2)`.
- [x] `requirements.txt`: added `openpyxl`, removed `junitparser`, kept `lxml` + the rest.
- [x] Canonical schema: `tdm_demo_output.csv` is in the repo (root) — fixtures build on it.
- [x] Baseline verified: `import test_data_mining.state` OK (18-key state, L1/L2/L3);
      `pytest` → "no tests ran" (exit 5, expected — v1 tests gone, v2 tests pending).

**Done when:** old nodes removed, new `state.py` imports cleanly, deps updated. ✅
**Note:** `graph.py`, `backend/app.py`, `nodes/ingest.py`, `nodes/persist.py` still reference the
old shape and are intentionally non-functional now — they're rewritten/split in Phases 1, 4, 7.
The working v1 lives on the `v1` branch.

---

## Phase 1 — Inputs (`parse` + `load_results`)
*Goal: turn the two input buckets into structured state. Pure, unit-testable, no stores/LLM.*

- [x] `nodes/parse.py` — reads `test_cases/` (csv/xlsx → headers=fields, scenario/id columns excluded;
      json → schema detect; txt → Gherkin `<placeholders>` + scenario keywords). Category/constraint
      inference per field. → `parsed_fields`. Never crashes → `gaps`.
- [x] `nodes/load_results.py` — parses JUnit XML (`<property>`) + Playwright JSON (`annotations`) →
      `result_signals` (tag, type, outcome, fields exercised) + `seed_values` (PASSING-run values only).
      No `results/` dir → empty + gap (unseeded).
- [x] Unit tests for both (csv/json/txt parse, category inference, passing-only seeds, malformed/empty → gaps).

**Done when:** given the sample inputs, `parse` lists the fields and `load_results` yields signals + seeds. ✅
**Verified:** 8 tests pass.

---

## Phase 2 — Sample data + data-gathering stores
*Goal: realistic seed so the demo tells a story; wire the read-only mine of Mongo + Chroma.*

- [x] Rewrote `scripts/generate_fixtures.py` (pivot §9): from `tdm_demo_output.csv` it seeds
      **MongoDB** (`data/sample_mongo/*.json`), **ChromaDB** (`data/sample_chroma/`, offline
      deterministic embeddings), supporting **results** (`results/junit.xml` valid-pass + negative-fail,
      `results/playwright.json` valid-pass; boundary/edge absent → gaps), primary **inputs**
      (`order_flow_tests.csv`, `login_flow_tests.txt`), and `golden/expectations_v2.json`.
- [x] Added shared offline embedder `src/test_data_mining/embedding.py` (stable md5 hashing, L2-norm)
      + a ChromaDB-compatible `DeterministicEmbeddingFunction` (no model download).
- [x] `nodes/mongo_lookup.py` — field-overlap / test-case-id match; `MONGODB_URI` or local
      `data/sample_mongo/`. Unreachable/empty → `existing_data=[]` + gap. 🔒 read-only.
- [x] `nodes/vector_search.py` — embed field names, ChromaDB top-K (K=5) cosine; threshold tuned
      to **0.40** for the offline embedder (env `CHROMA_THRESHOLD`; ~0.70 with real embeddings).
      Unreachable/empty → `retrieved_data=[]` + gap.
- [x] Unit tests incl. graceful degradation (no Mongo / no Chroma) — `test_mongo_lookup`, `test_vector_search`.

**Done when:** with seeded fixtures, `mongo_lookup` returns existing rows and `vector_search` returns similar ones. ✅
**Verified:** 14 tests pass; on real fixtures `mongo_lookup` → 2 datasets, `vector_search` → `order_flow` (sim 0.59).

---

## Phase 3 — Coverage gaps + generation
*Goal: the analytical + generative core (deterministic default, LLM seam).*

- [x] `nodes/coverage_gap.py` — matrix `required fields × {valid,boundary,negative,edge}` minus what
      `result_signals` exercised → `coverage_gaps` (a scenario that ran-but-failed counts as exercised).
- [x] `nodes/generate.py` — per field: `gen_A` valid-leaning (seeded from real values, **Gemini-enriched
      when available**, constraint-validated), `gen_B` gap-filling (targets the field's gaps), plus
      pass-through `existing`/`retrieved` sets. 🔒 anti-hallucination: valid values validated against
      constraints. LLM seam `generate(state, llm=None)`; offline default = deterministic, seeded.
- [x] Unit tests: gaps from signals; constraint-valid sets; gap-filling targets the gap (`test_coverage_gap`, `test_generate`).

**Done when:** `generate` emits `candidate_sets` (FieldCandidates) with valid + gap-filling variants. ✅
**Verified:** 18 tests pass; full Phase 1–3 chain on real fixtures → 27 gaps (boundary/edge), per-field
gen_A (seeded) + gen_B (gap-filling) + existing/retrieved sets (e.g. `currency` gen_A USD/GBP/INR, gen_B usd/JPY/BRL).

---

## Phase 4 — Graph wiring + backend `/mine` + `/resume`  🎯
*Goal: the pipeline runs to the (always-on) review interrupt; a programmatic resume completes it.*

- [x] `graph.py` — `parse → load_results → mongo_lookup → vector_search → coverage_gap → generate
      → review → synthesise → persist`; `review` always interrupts (L2-only). **Data-gather wired
      sequentially** (not parallel) — a staggered fan-in into `generate` re-ran upstream nodes on
      resume; single-parent chain keeps interrupt/resume clean. Also added `nodes/review.py`
      (interrupt payload + `auto_selections` for non-UI resume) ahead of schedule.
- [x] `nodes/synthesise.py` — assembles `final_dataset` rows from the chosen set per field; report
      (row count, source mix, gaps-filled fields, recommendations). Optional Gemini narrative seam.
- [x] `backend/app.py` — `POST /mine` (two buckets `test_cases[]` + `results[]` + pasted `text`)
      streams NDJSON to the `interrupt`; `POST /resume` (`review_selections` JSON) streams to the
      `result`; `/health`. Upload guards (size caps, per-bucket allow-list, cleanup).
- [x] Verified: graph CLI + backend tests — `/mine` streams to the gate, `/resume` returns a dataset
      (6 rows on the sample). 23 tests pass.

**Done when:** a `/mine` run streams to the review gate and a `/resume` returns a generated dataset. ✅

---

## Phase 5 — Frontend core (upload → mine → trace)
*Goal: the clickable front half — upload, stream the trace to the review gate. (No autonomy
selector — this agent is L2-only.)*

- [x] `InputPanel.jsx` — two buckets: **Test cases** (.xlsx/.csv/.json/.txt) + **Test results
      (optional)** (.xml/.json), multi-file accumulate/dedupe + per-file remove, optional paste box.
      No autonomy selector (L2-only).
- [x] `TracePanel.jsx` — reused (node-agnostic); now shows the v2 node names from the stream.
- [x] `ReportView.jsx` — CSV-oriented dataset preview (table), source-mix + gaps stats, recommendations,
      **Download CSV / JSON**.
- [x] `api.js` (`mine` + `resume`, NDJSON reader), `download.js` (CSV primary, JSON secondary).
- [x] `App.jsx` — orchestrates mine → trace → review-gate banner (interactive ReviewGate is Phase 6)
      → report. Builds clean (`npm run build`).

**Done when:** upload test cases (+ results) → Mine → trace streams to the review interrupt. ✅
**Note:** the run completes in the browser once Phase 6 adds the interactive ReviewGate + resume.

---

## Phase 6 — Set-based HITL review gate  🎯
*Goal: the defining v2 interaction — pick one value set per field — completing the clickable loop.*

- [x] `nodes/review.py` — per-field interrupt payload + selection mapping (done in Phase 4).
- [x] `ReviewGate.jsx` — per-field **radio** sets (mutually exclusive) with values preview, ⚠ gap
      badge, include checkbox, **Custom** values option, "Generate Final Dataset" → `/resume`.
- [x] `App.jsx` resume path: selections → `/resume` → trace continues → `ReportView` renders the
      dataset; **Download CSV/JSON**.

**Done when:** a run pauses at the gate, the analyst picks sets per field, and the downloaded CSV reflects the choices. ✅
**Verified:** realistic end-to-end over the ASGI app — mixed picks (email→existing, order_total→gen_B
boundary, coupon_code excluded) → 6 rows × 12 fields, source mix existing 8% / generated 92%. 23 tests pass; build clean.

---

## Phase 7 — Save-back loop  🎯
*Goal: persist chosen datasets and close the reuse loop.*

- [x] `nodes/persist.py` — `write_dataset()` writes the dataset (label + tags + field→values) to
      **MongoDB** (`MONGODB_URI`) or a local seed in `data/sample_mongo/` (same dir `mongo_lookup`
      reads — closes the loop) and **upserts** the case into **ChromaDB**. 🔒 no Neo4j, no `KG_SIGNAL_*`.
      The graph `persist` node only writes if `persist_decision` is pre-set (gate is the endpoint).
- [x] Backend `POST /persist` — `{session, save, label, tags}` reads the session's `final_dataset`
      from the checkpoint and calls `write_dataset` when `save` is truthy; else `{"saved": false}`.
- [x] `PersistGate.jsx` — label + tags + Save/Skip; shows the save receipt (location + Chroma index).
- [x] Verified the loop: `write_dataset(... "order_flow_v2")` → `mongo_lookup` finds `order_flow_v2`
      on a fresh state (`test_persist`), plus backend `/persist` save + skip tests.

**Done when:** a generated dataset can be saved and is reused by `mongo_lookup`/`vector_search` on the next run. ✅
**Verified:** 27 tests pass; frontend builds.

---

## Phase 8 — Tests, polish, demo dry-run  🎯
- [x] Unit tests per node + integration test (`test_integration.py`: full pipeline interrupt/resume,
      save→reuse loop, unseeded-when-no-results).
- [x] Adversarial (`test_adversarial.py`): malformed JSON/XML, no result files (unseeded), MongoDB
      unreachable, ChromaDB missing — all degrade with gap notes, no crash.
- [x] Polish: silenced the LangGraph msgpack forward-compat warnings; refreshed README + run_demo
      launchers for v2 (two-bucket inputs).
- [x] Dry-run: CLI (`python -m test_data_mining.graph --input data/sample_upload`) and the realistic
      backend end-to-end both run clean — 27 gaps, mixed-set selection → CSV, save→reuse.

**Done when:** the demo story runs start-to-finish on a clean checkout without manual fixups. ✅
**Verified:** 35 tests pass, 0 warnings; frontend builds; CLI + API dry-runs clean.
**Known limitation:** `synthesise` zips chosen sets into rows but doesn't enforce cross-field
scenario coherence (a row may pair a valid email with a boundary order_total) — fixed in Phase 9.

---

## Phase 9 — Additive + schema-agnostic output fix  🎯
*Goal: fix the headline output defects (50 rows in → 6 placeholder rows out). Authoritative spec:*
*[`IMPROVEMENT.md`](IMPROVEMENT.md). Make the agent additive, always-larger, schema-agnostic, and*
*LLM-coherent — without hardcoding any column names.*

> 🔒 **New invariants (CLAUDE.md #7–10):** additive (never subtractive) · always larger
> (`output > input`) · schema-agnostic (output columns == uploaded columns, no hardcoded names) ·
> coherent new rows (LLM generates each row whole). These join the existing six.

- [x] `parse.py` — emits `input_rows` (full raw rows, verbatim), `input_columns` (exact names/order),
      `input_row_count` into state (new `state.py` keys). `_select_primary()` picks the upload's
      primary table (most rows wins; merges files sharing identical headers); `.txt`/schema-only
      inputs contribute fields but no rows. The originals survive to `synthesise`.
- [x] `synthesise.py` (rewritten) — output = `input_rows` (untouched) **+** new rows appended.
      Deleted `_MAX_ROWS`/the `n = min(max(...))` cap. Uses `input_columns` for every row (falls back
      to chosen field names only when there's no tabular upload). Tags `scenario_tag`/`data_category`
      **only if** those columns exist. Generates each new row **whole via the LLM** (`_llm_rows_by_type`:
      prompt = input columns + sample real rows, per scenario type) for cross-field coherence;
      per-column deterministic fallback (`_det_row`) offline. Guard `assert len(final_dataset) >
      input_row_count`. `EXPANSION_FACTOR = 3` (optional ~3× target).
- [x] `generate.py` — raised `_MAX` 6 → 24; removed `_GENERIC` `sample_value_*` placeholders;
      added schema-agnostic per-column `_synth()` (constraint/category-driven) for unknown fields
      (demo `_VALID/_NEGATIVE/_BOUNDARY/_EDGE` tables kept only as a deterministic seed for known
      names); added `_is_placeholder()` guard rejecting `sample_value_*` / `generated_\d+` / `test_*`
      from seed/existing/retrieved data.
- [x] `generate_fixtures.py` — `--source <file>.csv` arg (default `tdm_demo_output.csv`); derives
      reused fields via `_reused_fields()`; optional identity dataset only when those fields exist;
      `_assert_no_placeholders()` after seeding.
- [x] **No change:** `coverage_gap.py`, `mongo_lookup.py`, `vector_search.py`, `review.py`, `persist.py`.
- [x] New acceptance suite `tests/test_additive_output.py` (7 tests): larger+additive, columns ==
      upload, no placeholders, honest tags, scenario columns never invented, both modes expand,
      excluded field keeps its column.

**Done when (acceptance, IMPROVEMENT.md §8):** for any uploaded CSV, Mode A (with XML) and Mode B
(without): `output_rows > input_rows`; every original row appears unchanged; no dedupe/clean/reformat;
output columns == uploaded columns exactly (any count/names, same order); when `data_category` exists,
new rows span valid/boundary/negative/edge and are honestly tagged (never `generated_NNN`); zero
`sample_value_*` placeholders; LLM rows internally coherent; expands in both modes. ✅
**Verified:** 42 tests pass (35 existing + 7 new). CLI dry-run on the seeded demo: **20 rows in →
60 out** (20 original preserved + 40 generated), 14 columns intact. LLM whole-row path confirmed via
a stub (originals verbatim, generated rows coherent, honest `valid_001`/`valid` tags enforced).

---

## Fastest demo path
Pivot §12: `state → parse → load_results → generate_fixtures → mongo_lookup → vector_search →
coverage_gap → generate → graph → backend/mine → ReviewGate → ReportView → PersistGate → api/download`
→ full upload → mine → choose-sets → CSV → save loop at L2.

---

*References: [`TDM-PIVOT-v2.md`](TDM-PIVOT-v2.md) (authoritative) · [`IMPROVEMENT.md`](IMPROVEMENT.md)
(Phase 9 fix spec) · [`demo-overview.md`](demo-overview.md) (framing) · `tdm_demo_output.csv`
(shape reference only) · [`CLAUDE.md`](../CLAUDE.md) (invariants).*
