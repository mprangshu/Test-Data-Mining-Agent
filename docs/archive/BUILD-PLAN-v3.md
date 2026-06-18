# BUILD-PLAN-v3.md — Coherence · Provenance · Iteration · Real Embeddings

> **What this is:** the detailed, file-level TODO for the **v3 work**. It merges two specs:
> - **[`IMPROVEMENT-2.md`](IMPROVEMENT-2.md)** — make the NEW rows *coherent* (schema-agnostic).
> - **[`CONTEXT-v3.md`](CONTEXT-v3.md)** — grounded generation, per-row *provenance*, an
>   *iterative* generate→pick→generate-more loop, and *real embeddings* (`all-MiniLM-L6-v2`).
>
> **Predecessors (still in force):** [`IMPROVEMENT.md`](IMPROVEMENT.md) + Phase 9 of
> [`BUILD-PLAN.md`](BUILD-PLAN.md) gave us *additive · always-larger · schema-agnostic · no
> placeholders*. v3 keeps all of that and fixes the remaining half (coherence) + adds the four
> CONTEXT-v3 features.
>
> 🔒 **Invariants that DO NOT change** (CLAUDE.md): read-only until the persist gate · MongoDB +
> ChromaDB, **no Neo4j** · deterministic-before-LLM · graceful degradation · **never hardcode
> column names or per-domain coherence rules** (the schema + its relationships are *learned from
> the uploaded data*).

## Legend
`[ ]` to do · `[x]` done · 🔒 invariant checkpoint · 🎯 demoable milestone · ⚠ risk

---

## Where we are now (baseline going into v3)

**Working (Phase 9 / `IMPROVEMENT.md`):** output = originals (verbatim) + new rows; always larger;
output columns == uploaded columns; no `sample_value_*`; LLM whole-row path exists in
`synthesise.py` (`_llm_rows_by_type`); deterministic offline fallback exists (`_det_row`).

**Still broken (`IMPROVEMENT-2.md`, the reason for v3):** the **offline `_det_row` path index-zips
columns**, so new rows are incoherent — mismatched country/currency, `free` plans with non-zero
amounts, duplicate primary keys, no `valid` rows (gap-weighting drops them), tag≠content. The LLM
path is better but still needs: scenario-aware prompting, unique-id minting, mostly-empty-stays-empty,
and grounding on fetched+gathered (not just the uploaded originals).

**Two things the deterministic embedder can't do** (`CONTEXT-v3 §4`): the md5 hash embedder gives
weak, meaningless cosine scores (we tuned the threshold to 0.40 to compensate). Real embeddings
(`all-MiniLM-L6-v2`) make `vector_search` (= "gathered") actually meaningful.

---

## Status at a glance

| Phase | Outcome | Depends on | Layer |
|---|---|---|---|
| 0 | ✅ Prerequisites & de-risking: specs saved, MiniLM installed + **offline-load verified** (384-dim, related>unrelated) | — | setup |
| 1 | ✅ Real embeddings: `all-MiniLM-L6-v2` (384-dim) at all 3 sites + richer context; Chroma re-seeded; threshold tuned to **0.40** | 0 | backend |
| 2 | ✅ **Coherent + grounded generation** (clone-and-perturb + LLM whole-row + unique ids + scenario mix); row count relaxed 🎯 | 1 | backend |
| 3 | ✅ Provenance in API + clean CSV: `OutputRow`(fields+source+uid); row-aligned store data; CSV stays clean | 2 | backend |
| 4 | ✅ Iterative loop: `POST /generate-more` seeded by user selection; replace semantics; `round_index` | 3 | backend |
| 5 | ✅ Frontend: per-row source display (colour/badge + legend + filter chips) | 3 | frontend |
| 6 | ✅ Frontend: per-row selection + "generate more from selected" loop 🎯 | 4,5 | frontend |
| 7 | ✅ Frontend: clean CSV download (fields only) + optional CSV+sources debug export | 5 | frontend |
| 8 | ✅ Tests & universality: second-schema CSV (loans + sensors), offline embeddings, full matrix 🎯 | all | tests |

---

## Open questions — confirm with senior before Phase 3/6 (defaults chosen so we can proceed)

| # | Question | Working default (used unless told otherwise) |
|---|---|---|
| Q1 | Show original uploaded rows tagged `input`, or hide them? | ✅ **CONFIRMED: Show, tagged `source="input"`** (4th tag) so "your data" is distinct from the 3 generated sources |
| Q2 | "Generate more" — append to the set, or replace it? | ✅ **CONFIRMED: Replace each round** — every "generate more" starts a fresh set seeded by the picked rows; `round_index` still tracks the iteration |
| Q3 | Final CSV — all kept rows, or only generated? | ✅ **CONFIRMED: All kept rows** (originals + kept generated/fetched/gathered) — "the sheet is all data" |
| Q4 | Local `all-MiniLM-L6-v2` path? | ✅ **CONFIRMED: use the pinned snapshot** `models--sentence-transformers--all-MiniLM-L6-v2/snapshots/c9745ed…/` (auto-resolved; `EMBED_MODEL_PATH` overrides) |

> All four confirmed by the user. **Note Q2 = Replace (not append)** — Phase 4 builds replace semantics.

---

## Phase 0 — Prerequisites & de-risking
*Goal: clear the unknowns before writing feature code, so no phase stalls mid-build.*

- [x] Save the two source specs into `docs/` (`IMPROVEMENT-2.md`, `CONTEXT-v3.md`) — done with this plan.
- [x] ⚠ **Install embedding stack:** added `sentence-transformers>=2.2,<4` to `requirements.txt`;
      installed (`torch 2.12.1+cpu`, `transformers`, `tokenizers`, `scipy`, `scikit-learn`). Install
      succeeded on this network — no TLS failure. (A transient "DLL load failed (_C)" appeared
      mid-install and resolved once the install completed.)
- [x] **Verify offline load:** [`scripts/check_embedding_offline.py`](../scripts/check_embedding_offline.py)
      forces `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`, loads `SentenceTransformer(<local snapshot>)`,
      encodes offline → **384-dim**; `cosine(order,order)=0.388` ≫ `cosine(order,sensors)=0.025`. PASS.
- [x] Snapshot pinned: `EMBED_MODEL_PATH` →
      `models--sentence-transformers--all-MiniLM-L6-v2/snapshots/c9745ed1d9f207416be6d2e6f8de32d1f16199bf`
      (the complete one — `model.safetensors` + `pytorch_model.bin` + tokenizer). The check script
      auto-resolves this when the env var is unset.
- [ ] Send the senior Q1–Q4 (above). Proceed on the defaults meanwhile. *(awaiting you)*

> ⚠ **Threshold finding (carry into Phase 1):** real MiniLM cosines on our SHORT field-name text
> are modest — related ≈ **0.39**, unrelated ≈ 0.03. CONTEXT-v3's suggested `~0.70` is **too high**
> for this input; tune empirically, likely **~0.30–0.45**. Embedding richer context (field names +
> sample values + tags) would raise the spread and allow a higher threshold.

**Done when:** ✅ `sentence-transformers` imports, the local model encodes offline to 384-dim, the
model path is pinned. **Fallback (unused — install worked):** the deterministic embedder stays as a
runtime auto-fallback for environments where the model/stack can't load.

---

## Phase 1 — Real embeddings swap  (backend, isolated)
*Goal: meaningful similarity so "gathered" (ChromaDB) data is actually relevant.*

Files: `src/test_data_mining/embedding.py`, `nodes/vector_search.py`, `nodes/persist.py`,
`scripts/generate_fixtures.py`.

- [x] `embedding.py` — added lazy offline singleton `_load_st_model()` (resolves `EMBED_MODEL_PATH`
      or the in-repo snapshot, `HF_HUB_OFFLINE=1`), `LocalMiniLMEmbeddingFunction`, and the public
      API `embed_text`/`embed_texts`/`get_embedding_function`/`active_embedder_name`. **Kept
      `DeterministicEmbeddingFunction`/`embed()` as an auto-fallback** when the model can't load
      (invariant #4). Added `context_text()` — the richer-context builder (option 2).
- [x] Replaced the embedder usage in `vector_search.py`, `persist.py`, `generate_fixtures.py` with
      the factory + `context_text` (no 384/dim hardcoded anywhere).
- [x] `vector_search.py` — query is now the descriptive `context_text(field names + categories)`;
      threshold **tuned to 0.40** per embedder (NOT 0.70 — measured: relevant 0.40–0.60, unrelated
      ≤0.37; `scripts/measure_similarity.py`). Env `CHROMA_THRESHOLD` still overrides.
- [x] `generate_fixtures.py` — re-seeds ChromaDB with the active embedder; docs embed
      title+tags+fields+sample values via `context_text`.
- [x] Tests: `test_vector_search.py` made embedder-agnostic (seeds with the active embedder so dims
      always match). Added `scripts/check_embedding_offline.py` (offline load + 384-dim +
      related>unrelated) and `scripts/measure_similarity.py` (threshold tuning).

**Done when:** ✅ `vector_search` returns sensible neighbours on real data (order query → both order
datasets 0.60/0.41; sensor query → none ≥0.40); suite green; everything runs offline.
**Verified:** 42 tests pass with the real embedder; CLI end-to-end → `mongo_lookup` 2 datasets +
`vector_search` **2 similar cases** (up from 1 with the hashed embedder) → additive 20→60 output.
⚠ **Risk (retired):** model download / corporate TLS — install + offline load both succeeded in Phase 0.

---

## Phase 2 — Coherent + grounded generation  (backend) 🎯
*Goal: the heart of v3. New rows are coherent whole records, grounded in user input + fetched +
gathered — with **zero hardcoded column names or domain rules**.*

Files: `src/test_data_mining/inference.py` (new), `nodes/synthesise.py` (rewritten).
**Scoping note:** the six defects all live in the row *assembler* (`synthesise.py`), so the work
landed there + the new `inference.py`. `generate.py` (per-field candidate sets for the HITL gate)
was left as-is — it already seeds from real values and falls back to constraint-driven `_synth`
(no `sample_value_*`), and row coherence is now owned entirely by `synthesise`.

**2a — Data-driven inference helpers (new `inference.py`)** — IMPROVEMENT-2 §2
- [x] `infer_column_type(values) → numeric|datetime|id|categorical|freetext|empty` — by **content,
      not name**. `ColProfile` + `profile_columns` capture type, fill_rate, observed values, id
      pattern, numeric range, code-like shape.
- [x] `id_pattern()` + `IdMinter` — continue the observed `PREFIX-<number>` sequence, never reuse
      an existing id (fixes Defect 5).
- [x] `cooccurrence()` + `correlated_pairs()` — statistical coherence groups for the offline path
      (IMPROVEMENT-2 §2c), used to preserve learned links (e.g. country↔currency) on edge swaps.

**2b — Whole-row generation (rewrote the NEW-row builder in `synthesise.py`)** — IMPROVEMENT-2 §1
- [x] **Primary (LLM):** `_llm_rows()` prompts with exact columns + real example rows + **known real
      values per column merged from originals + analyst picks + fetched (Mongo) + gathered (Chroma)**
      so the model infers relationships and grounds on stored data (CONTEXT-v3 §2). Per scenario;
      JSON validated → coerced to exact columns; per-row fallback on shortfall.
- [x] **Fallback (offline/tests):** `_perturb()` replaces index-zip with **clone-a-real-row-then-
      perturb-minimally** — valid=clone (+refresh datetimes); boundary=numeric min/max;
      negative=empty exactly one high-fill field; edge=one unusual observed value (carrying
      correlated partners). Coherence comes from the cloned real row.
- [x] **Unique ids:** id columns always re-minted in new rows — even when the LLM supplies an id.
- [x] **Optional/empty fields:** cloning preserves real emptiness; mostly-empty columns stay mostly
      empty; never a bare `1,2,3` counter (Defect 3).

**2c — Scenario mix + honest tags** — IMPROVEMENT-2 §3
- [x] `_scenario_plan()` weights valid≥2 and shifts toward `coverage_gaps`, but **never drops valid**
      (fixes Defect 4). Replaced the old gap-only sequence.
- [x] Tag = content: `scenario_tag`/`data_category` written only if those columns exist; the tag
      matches how the row was generated (fixes Defect 6).

**2d — Relax the row-count rule** — CONTEXT-v3 §1
- [x] Dropped the hard `> input` EXPANSION assertion. Soft target `n_new = max(input_rows, 5)`
      (output ~2×); guard only against "too few" (`>= input`); no upper cap.

**Done when:** ✅ new rows coherent (country/currency match, no `free`+nonzero), ids unique, valid
present, tags match content — **no subscription names in code**; originals verbatim; output ≥ input.
**Verified:** new `tests/test_coherence.py` (6 tests) — unique ids continue pattern, valid present,
valid rows coherent, optional column stays mostly empty, **second schema (loans) with zero
cross-domain artifacts**, additive. LLM-grounded path confirmed via stub (coherent rows, ids
re-minted unique, shortfall → clone-perturb). Full suite: **48 passed** with the real embedder.

---

## Phase 3 — Provenance in the API + clean CSV  (backend)
*Goal: every row knows its origin for the UI; the downloaded file stays clean.*

Files: `src/test_data_mining/state.py`, `nodes/synthesise.py`, `backend/app.py`,
`frontend/src/download.js` (export helper).

- [x] `state.py` — added `OutputRow {fields, source, row_uid}` + `RowSource` literal; added
      `output_rows`, `round_index`, `seed_selection`; added optional `rows: list[dict]` to
      `ExistingRecord`/`RetrievedRecord` (row-aligned store data). `final_dataset` is the clean
      projection `[r.fields for r in output_rows]` (no source/uid).
- [x] **Row-aligned store data** (foundation for coherent fetched/gathered): `generate_fixtures`
      and `persist.write_dataset` now store a `rows` array per dataset; `mongo_lookup`/`vector_search`
      read it back into the records. This also improves Phase 2 grounding (real coherent rows).
- [x] `synthesise.py` — emits `output_rows`: originals → `input` (verbatim); generated → `generated`;
      MongoDB rows → `fetched`; ChromaDB rows → `gathered`. Generated/fetched/gathered get freshly
      minted ids (PKs unique across the whole set); `row_uid = r{round}-{src}{i}`. Column TYPES are
      profiled from the originals (store rows repeat ids and would skew id detection).
- [x] `backend/app.py` — `_result_payload` returns `output_rows` (jsonable_encoder serialises the
      dataclasses) **with** `source` + `row_uid`, alongside the clean `final_dataset`/`report`.
- [x] CSV export already clean: `download.js downloadCsv` builds from `final_dataset` + `report.columns`
      (fields only) — no `source` column. No change needed (JSON export keeps provenance as a debug aid).
- [x] Tests: new `tests/test_provenance.py` (3) — output_rows carry source+unique uid (originals
      tagged input, verbatim); final_dataset clean (no source/uid, exact columns); fetched+gathered
      rows tagged with re-minted unique ids.

**Done when:** ✅ API gives per-row provenance; the CSV is clean test data with the original columns.
**Verified:** 51 tests pass (48 + 3) with the real embedder; fixtures re-seeded with row-aligned data.

---

## Phase 4 — Iterative loop  (backend)
*Goal: generate → user picks rows → those seed the next grounded round.*

Files: `backend/app.py`, `nodes/synthesise.py`.

- [x] `POST /generate-more` — accepts `{session, seed_selection}`: the picked rows become the new
      `input_rows` (the curated base), `round_index += 1`, and `synthesise` regenerates everything
      else grounded on them (+ the session's fetched/gathered). **REPLACE** semantics (Q2). Returns
      the new `output_rows` (tagged + fresh `row_uid`s) + clean `final_dataset` + report.
- [x] Read-only (no Mongo write); `/persist` stays the only write gate, now saving the **latest**
      round via `_latest_state()`.
- [x] `_ROUNDS[session]` holds the current round's working state (replaced each round); `_stream_events`
      captures the post-resume state into it so round 1 has a base; `/persist` prefers it.
- [x] Runs deterministic (llm=None), consistent with the graph path (the LLM seam isn't wired into
      the graph yet — activating Gemini graph-wide is a separate toggle).
- [x] Tests: new `tests/test_generate_more.py` (3) — replace round seeded by selection (round_index
      0→1→2, picked rows carry over as `input`, clean CSV), requires a selection (422), unknown session (404).

**Done when:** ✅ selecting rows + "generate more" yields a fresh grounded round seeded by the selection.
**Verified:** 3 new tests pass (full mine→resume→generate-more→generate-more over the ASGI app).

---

## Phase 5 — Frontend: provenance display  (UI)
*Goal: the QA engineer sees where every row came from.*

Files: `frontend/src/components/ReportView.jsx`, `api.js`, maybe a new `SourceBadge`/legend.

- [x] `ReportView.jsx` rewritten to render from `output_rows`: a leading **Source** badge column +
      per-row tint by source (input=slate, generated=indigo, fetched=emerald, gathered=amber), with a
      note that source is on-screen only (not in the CSV). Falls back to `final_dataset` if a response
      lacks `output_rows`.
- [x] **Legend + filter chips** (All / Input / Generated / Fetched / Gathered) with live counts;
      clicking a chip filters the previewed table by source.
- [x] `output_rows` already arrives in the `result` event (backend Phase 3) — `api.js` needs no change.
- [x] Round indicator in the header (`round N`) from `result.round_index`. Table read-only (selection
      is Phase 6). Build clean.

**Done when:** ✅ every row visibly shows its origin; the four sources are distinguishable at a glance.
**Verified:** `npm run build` succeeds (38 modules); ReportView reads `result.output_rows` with the
four-source colour scheme + filter.

---

## Phase 6 — Frontend: selection + iterate  (UI) 🎯
*Goal: close the loop in the browser.*

Files: `ReportView.jsx` (or a new `WorkingSetTable.jsx`), `App.jsx`, `api.js`.

- [x] Per-row checkbox + a header "select all in current filter" checkbox. Combined with the Phase 5
      filter chips, that gives **select-all-by-source** (filter to a source, select all). Selected
      row_uids tracked in `ReportView` state; selection resets when a new round arrives.
- [x] "↻ Generate more from selected" toolbar (count + clear) → `api.generateMore(session, rows)` →
      `POST /generate-more`; **replace** semantics (Q2). Round indicator already in the header
      (`round N`); repeatable.
- [x] `App.jsx` — `runGenerateMore(rows)` sets the new round's result; `generating` busy state;
      passes `onGenerateMore`/`generating` into `ReportView`. `api.js` gained `generateMore()`.

**Done when:** ✅ generate → pick rows → generate-more loops smoothly, rounds visible.
**Verified:** `npm run build` clean; the Phase 4 `/generate-more` endpoint it drives is covered by
`tests/test_generate_more.py` (round 0→1→2, replace, clean CSV).

---

## Phase 7 — Frontend: clean download  (UI)
*Goal: the exported sheet is clean test data.*

Files: `frontend/src/download.js`, `ReportView.jsx`.

- [x] "⬇ Download CSV" exports **fields only** — original columns, **no source column** — for the
      whole current working set (Q3: input + generated + fetched + gathered). Clean by construction
      (`downloadCsv` reads `final_dataset` + `report.columns`).
- [x] Secondary **"CSV + sources (debug)"** link (de-emphasised) via `downloadCsvWithSources` —
      prepends a `source` column from `output_rows`; clearly marked as debug. JSON export keeps full
      provenance too.

**Done when:** ✅ the downloaded file is clean; provenance lives only on screen (+ an opt-in debug export).
**Verified:** `npm run build` clean; clean CSV pulls from `final_dataset` (no `source`/`row_uid`),
confirmed by `tests/test_provenance.py`.

---

## Phase 8 — Tests & universality 🎯
*Goal: prove it's schema-agnostic and the whole loop holds.*

New tests: `test_coherence.py`, `test_provenance.py`, `test_generate_more.py`,
`test_embedding_local.py`, `test_universality_e2e.py` (+ Phase 9's `test_additive_output.py`).

- [x] **Universality:** `test_coherence.test_second_schema_loans` (direct nodes) **and**
      `test_universality_e2e` (full graph, IoT sensors) — expands, coherent, unique ids continuing the
      observed pattern, **zero order/subscription artifacts**, schema preserved, no scenario columns invented.
- [x] **Coherence:** `test_coherence` asserts country/currency match on valid rows + optional column
      stays mostly empty — no hardcoded rules.
- [x] **Provenance/CSV:** `test_provenance` — output_rows carry source+uid; `final_dataset` clean
      (no source/uid); fetched/gathered tagged with unique ids.
- [x] **Iterate:** `test_generate_more` — `/generate-more` seeded by a selection → new grounded round
      (round 0→1→2, replace).
- [x] **Embeddings offline:** `test_embedding_local` — active embedder encodes to the right dim
      (384 for MiniLM) and related > unrelated, with the network off.

**Done when:** ✅ the acceptance matrix is green on both schemas.

---

## Consolidated acceptance criteria (v3 end state)

| Check | Pass condition | Source |
|---|---|---|
| Coherence | new rows respect data-inferred relationships; no hardcoded rules | IMPROVEMENT-2 |
| Universality | works on a second different-schema CSV; zero subscription artifacts | IMPROVEMENT-2 |
| Unique ids | id-like columns unique across output; new ids continue observed pattern | IMPROVEMENT-2 |
| Valid present | new rows include valid + boundary + negative + edge (when category col exists) | IMPROVEMENT-2 |
| Tag = content | every new row's scenario tag matches its actual values | IMPROVEMENT-2 |
| Optional fields | mostly-empty stay mostly-empty; code-like match observed shape (no bare 1,2,3) | IMPROVEMENT-2 |
| Grounded | generated rows reflect user input + fetched + gathered (not invented blind) | CONTEXT-v3 |
| Provenance (UI) | every row shows source generated/fetched/gathered (+ input) on screen | CONTEXT-v3 |
| Clean CSV | downloaded file = original columns only; no `source`, no source-`data_category` | CONTEXT-v3 |
| Iterative | select rows → "generate more" → new grounded round seeded by selection | CONTEXT-v3 |
| Row count | output ≥ input rows (more fine); never "too few"; no hard cap | CONTEXT-v3 |
| Real embeddings | `all-MiniLM-L6-v2` at all 3 sites, offline; threshold ~0.70; Chroma re-seeded | CONTEXT-v3 |
| Still additive | originals verbatim; schema-agnostic; read-only until persist | IMPROVEMENT |

---

## Build order (recommended)
`Phase 0 (de-risk) → 1 (embeddings) → 2 (coherent+grounded) → 3 (provenance API) →
4 (generate-more) → 5 (UI source display) → 6 (UI select+iterate) → 7 (UI clean download) →
8 (tests/universality)`. Backend first so the frontend builds against real shapes. Phase 2 is the
biggest and most valuable; Phase 1 can be deferred behind the deterministic fallback if the model
install blocks.

---

*References: [`IMPROVEMENT-2.md`](IMPROVEMENT-2.md) · [`CONTEXT-v3.md`](CONTEXT-v3.md) (the two
authoritative specs) · [`IMPROVEMENT.md`](IMPROVEMENT.md) + [`BUILD-PLAN.md`](BUILD-PLAN.md) Phase 9
(predecessors) · [`CLAUDE.md`](../CLAUDE.md) (invariants).*
