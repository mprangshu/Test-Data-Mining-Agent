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
| 6 | Set-based HITL: `review` interrupt + `ReviewGate` radios + `/resume` → CSV report + download 🎯 | 5 |
| 7 | Save-back loop: `persist` (Mongo+Chroma) + `PersistGate`; re-run reuses saved data 🎯 | 6 |
| 8 | Tests (unit/integration/adversarial) + polish + demo dry-run 🎯 | all |

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

- [ ] `nodes/review.py` — build the per-field interrupt payload (pivot §5): each field with its
      2–3 sets (+ existing/retrieved), `gap_flagged`; `interrupt(payload)`; map resumed selections
      → `ReviewSelection`. (Always runs — L2-only.)
- [ ] `ReviewGate.jsx` — per-field **radio** sets (mutually exclusive), ⚠ gap badge, include
      checkbox, "+ Add custom field", "Generate Final Dataset" → `/resume`.
- [ ] Wire the frontend resume path so selections drive `synthesise`; render the CSV report + download.

**Done when:** a run pauses at the gate, the analyst picks sets per field, and the downloaded CSV reflects the choices.

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
- [ ] Unit tests per node; integration test (full pipeline; review interrupt/resume; persist loop).
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
