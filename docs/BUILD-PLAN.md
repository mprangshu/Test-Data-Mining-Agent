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
| 0 | Teardown + new `state.py` + deps; green (empty) baseline | — |
| 1 | Inputs parsed: `parse` (test cases) + `load_results` (results → signals + seeds) | 0 |
| 2 | Sample data + stores: `generate_fixtures` seeds Mongo/Chroma/inputs; `mongo_lookup` + `vector_search` | 1 |
| 3 | Gaps + generation: `coverage_gap` + `generate` (2–3 constraint-valid sets/field) | 2 |
| 4 | Graph wired + backend `/mine`; L1 end-to-end → `final_dataset` 🎯 | 3 |
| 5 | Frontend: two-bucket upload → mine → CSV report + download (L1) 🎯 | 4 |
| 6 | Set-based HITL: `review` interrupt + `ReviewGate` radios + `/resume` (L2) 🎯 | 5 |
| 7 | Save-back loop: `persist` (Mongo+Chroma) + `PersistGate`; re-run reuses saved data 🎯 | 6 |
| 8 | Tests (unit/integration/adversarial) + polish + demo dry-run 🎯 | all |

---

## Phase 0 — Teardown & new contract
*Goal: clear v1's analysis nodes, lay down the v2 state schema, keep the repo importable/green.*

- [ ] Delete v1 files (pivot §6): `nodes/flaky_detect.py`, `nodes/failure_clustering.py`,
      `nodes/synthesis.py`, `nodes/stubs.py`, `scripts/score_golden.py`,
      `tests/test_flaky_detect.py`, `tests/test_validate.py`, `tests/test_synthesis_persist.py`,
      `tests/test_failure_clustering.py`. (Keep `data/sample_upload/*` for reference; will be reshaped.)
- [ ] Rewrite `src/test_data_mining/state.py` to the v2 schema (pivot §4) — `ParsedField`,
      `ResultSignal`, `SeedValue`, `ExistingRecord`, `RetrievedRecord`, `CoverageGap`,
      `CandidateSet`, `FieldCandidates`, `ReviewSelection`, new `AgentState`. Keep `gaps`/`errors`
      accumulate-reducers.
- [ ] `requirements.txt`: add `openpyxl`; keep `lxml`, langgraph, chromadb, pymongo, fastapi, uvicorn, pytest.
- [ ] Decide the canonical schema: use `tdm_demo_output.csv` if present, else synthesise from the
      §9 column list (order-flow). Note the decision here.
- [ ] Baseline: `python -c "import test_data_mining.state"` imports; `pytest` collects (0 tests OK).

**Done when:** old nodes removed, new `state.py` imports cleanly, deps updated.

---

## Phase 1 — Inputs (`parse` + `load_results`)
*Goal: turn the two input buckets into structured state. Pure, unit-testable, no stores/LLM.*

- [ ] `nodes/parse.py` — read `test_cases/`: xlsx/csv → columns=fields (+ `scenario_type` if present);
      json → schema detect; txt → Gherkin `<placeholders>` + Given/When/Then → fields + scenarios.
      → `parsed_fields`. Never crash → `gaps`.
- [ ] `nodes/load_results.py` — parse JUnit XML + Playwright JSON → `result_signals` (scenario,
      outcome, fields touched) + `seed_values` (real values from **passing** runs). No results → empty + gap.
- [ ] Unit tests for both (xlsx/csv/json/txt parse; passing-run seed extraction; empty/malformed → gaps).

**Done when:** given the sample inputs, `parse` lists the fields and `load_results` yields signals + seeds.

---

## Phase 2 — Sample data + data-gathering stores
*Goal: realistic seed so the demo tells a story; wire the read-only mine of Mongo + Chroma.*

- [ ] Rewrite `scripts/generate_fixtures.py` (pivot §9): seed **MongoDB** (`data/sample_mongo/*.json`
      or live), **ChromaDB** (offline deterministic embeddings), supporting **result files**
      (valid pass → seeds; negative/boundary absent/failing → gaps), primary **input files**
      (`order_flow_tests.csv`, `login_flow_tests.txt`), and a small **golden expectation** file.
- [ ] `nodes/mongo_lookup.py` — match by test-case id / story key / field overlap; `MONGODB_URI` or
      local `data/sample_mongo/`. Unreachable/empty → `existing_data=[]` + gap. 🔒 read-only.
- [ ] `nodes/vector_search.py` — embed fields+story, ChromaDB top-K (K=5, threshold 0.70); reuse the
      v1 offline embedder. Unreachable/empty → `retrieved_data=[]` + gap.
- [ ] Unit tests incl. graceful degradation (no Mongo / no Chroma).

**Done when:** with seeded fixtures, `mongo_lookup` returns existing rows and `vector_search` returns similar ones.

---

## Phase 3 — Coverage gaps + generation
*Goal: the analytical + generative core (deterministic default, LLM seam).*

- [ ] `nodes/coverage_gap.py` — matrix `required fields × {valid,boundary,negative,edge}` minus what
      `result_signals` exercised → `coverage_gaps`.
- [ ] `nodes/generate.py` — per field, 2–3 `CandidateSet`s: `gen_A` valid-leaning (seeded),
      `gen_B` boundary/negative (gap-filling), optional `gen_C` edge; pass through `existing`/`retrieved`
      as selectable sets. 🔒 every value constraint-valid (regen on failure). LLM seam
      `generate(state, llm=None)`; offline default = deterministic faker seeded by real values.
- [ ] Unit tests: gaps detected from signals; sets are constraint-valid; gap-filling set targets the gap.

**Done when:** `generate` emits `candidate_sets` (FieldCandidates) with valid + gap-filling variants.

---

## Phase 4 — Graph wiring + backend `/mine`  🎯
*Goal: the deterministic pipeline runs end-to-end and the API returns a dataset (L1, no HITL yet).*

- [ ] `graph.py` — `parse → [load_results | mongo_lookup | vector_search] → coverage_gap → generate
      → (review if L2) → synthesise → persist`; L1/L3 skip review (L1 auto-picks widest-coverage set).
- [ ] `nodes/synthesise.py` (interim auto-select for L1) — assemble `final_dataset` rows from chosen
      sets; align by scenario; resolve cross-field constraints; write `report` (totals, source mix,
      coverage map, gaps).
- [ ] `backend/app.py` — `POST /mine` (two buckets `test_cases[]` + `results[]`, multipart/JSON),
      stream NDJSON node events; `/health`. Reuse v1 streaming + guards (size caps, allow-list, cleanup).
- [ ] Verify (CLI + curl): sample inputs → `final_dataset` rows shaped like the canonical CSV.

**Done when:** an L1 `/mine` run streams the trace and returns a generated dataset.

---

## Phase 5 — Frontend core (upload → mine → CSV)  🎯
*Goal: the clickable loop at L1.*

- [ ] `InputPanel.jsx` — two file groups: **Test cases** (.xlsx/.csv/.json/.txt) and **Test results
      (optional)** (.xml/.json); keep multi-file accumulate/dedupe.
- [ ] `TracePanel.jsx` — new node names (parse · load_results · mongo_lookup · vector_search ·
      coverage_gap · generate · review · synthesise · persist).
- [ ] `ReportView.jsx` — CSV-oriented dataset preview + coverage-gap section + source-mix summary.
- [ ] `api.js` (`/mine`, `/resume`, `/persist`), `download.js` (CSV primary, JSON secondary).

**Done when:** upload test cases (+ results) → Analyse → see generated rows → download CSV (L1).

---

## Phase 6 — Set-based HITL review gate (L2)  🎯
*Goal: the defining v2 interaction — pick one value set per field.*

- [ ] `nodes/review.py` — build the per-field interrupt payload (pivot §5): each field with its
      2–3 sets (+ existing/retrieved), `gap_flagged`; `interrupt(payload)`; map resumed selections
      → `ReviewSelection`. Skipped at L1/L3.
- [ ] Backend `/resume` — `{session_id, review_selections}` → `Command(resume=…)` → stream to result.
- [ ] `ReviewGate.jsx` (rewrite) — per-field **radio** sets (mutually exclusive), ⚠ gap badge,
      include checkbox, "+ Add custom field", "Generate Final Dataset".
- [ ] `synthesise` honours chosen sets; 🔒 verify L1/L3 skip the gate, only L2 pauses.

**Done when:** an L2 run pauses, the analyst picks sets per field, and the dataset reflects the choices.

---

## Phase 7 — Save-back loop  🎯
*Goal: persist chosen datasets and close the reuse loop.*

- [ ] `nodes/persist.py` — on `save=true`: write dataset (+ label + tags) to MongoDB and **upsert**
      into ChromaDB for future retrieval; local JSON fallback. 🔒 no Neo4j, no `KG_SIGNAL_*`.
- [ ] Backend `/persist` — `{session_id, save, label?, tags?}` → calls `persist` when `save=true`.
- [ ] `PersistGate.jsx` (new) — label + tags + Save/Skip.
- [ ] Verify the loop: save as `order_flow_v2` → re-run → `mongo_lookup` now finds it.

**Done when:** a generated dataset can be saved and is reused by `mongo_lookup`/`vector_search` on the next run.

---

## Phase 8 — Tests, polish, demo dry-run  🎯
- [ ] Unit tests per node; integration test (full pipeline per autonomy; L2 interrupt/resume; persist loop).
- [ ] Adversarial: empty MongoDB (LLM-only path), no result files (unseeded), malformed inputs, no Chroma.
- [ ] One-command startup + README refresh; rehearse the pivot §13 demo story end-to-end.

**Done when:** the demo story runs start-to-finish on a clean checkout without manual fixups.

---

## Fastest demo path
Pivot §12: `state → parse → load_results → generate_fixtures → mongo_lookup → vector_search →
coverage_gap → generate → graph → backend/mine → ReviewGate → ReportView → PersistGate → api/download`
→ full upload → mine → choose-sets → CSV → save loop at L2.

---

*References: [`TDM-PIVOT-v2.md`](TDM-PIVOT-v2.md) (authoritative) · [`demo-overview.md`](demo-overview.md)
(framing) · `tdm_demo_output.csv` (canonical schema) · [`CLAUDE.md`](../CLAUDE.md) (invariants).*
