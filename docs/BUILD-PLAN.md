# BUILD-PLAN.md — How to build the demo, phase by phase

> **What this is:** the practical, ordered TODO to get from today's working deterministic
> core to the clickable demo described in [`demo-overview.md`](demo-overview.md). It
> complements [`ROADMAP.md`](ROADMAP.md) (which tracks the *agent* node-by-node) by adding
> the **API + React UI** layers and sequencing everything into demoable slices.
>
> **Guiding principle — vertical slices.** Every phase ends in something you can *run and
> show*. We wire a thin end-to-end path early (even with placeholder LLM output), then
> enrich it. We do **not** build all the agent internals before the first screen works.
>
> 🔒 **Invariants hold at every phase:** read-only · no Neo4j/graph DB · deterministic
> detectors before LLM · graceful degradation (never crash). See [`CLAUDE.md`](../CLAUDE.md).

## Legend
- [ ] to do · [x] done · 🔒 invariant checkpoint · 🎯 demoable milestone

## Status at a glance

| Phase | Outcome | Depends on |
|---|---|---|
| 0 | ✅ Green baseline — env set up, core tests + golden score pass | — |
| 1 | ✅ Agent runs end-to-end on fixtures (placeholder LLM) 🎯 | 0 |
| 2 | ✅ Backend `/analyse` returns a report from uploaded/pasted data 🎯 | 1 |
| 3 | ✅ React page: upload/paste → Analyse → report → Download 🎯 | 2 |
| 4 | ✅ Live agent-trace panel (streaming) 🎯 | 3 |
| 5 | ✅ Real failure clustering (ChromaDB) + grounded labels (LLM seam) | 1 |
| 6 | ✅ Synthesis (ranked + grounded, LLM seam) + persistence | 5 |
| 7 | ✅ L2 HITL review gate wired through the UI 🎯 | 4, 6 |
| 8 | ✅ Polish, tests, demo dry-run 🎯 | all |

---

## Phase 0 — Setup & green baseline
*Goal: prove the existing deterministic core works on this machine before adding anything.*

- [x] Create and activate a virtualenv (`python -m venv .venv`).
- [x] `pip install -r requirements.txt` (langgraph 1.2.5, chromadb 1.5.9, langchain-core, pymongo, pytest…).
- [x] `python scripts/generate_fixtures.py` → fixtures + golden labels exist in `data/` (10 runs × 40 tests).
- [x] `pytest -q` → green (3 passed).
- [x] `python scripts/score_golden.py` → **PASS** (precision 0.857 ≥ 0.85, recall 1.000 ≥ 0.75).
- [x] Confirm `from test_data_mining.graph import build_graph` imports + compiles (`CompiledStateGraph`).

**Done when:** tests green + golden score PASS + graph imports. No code written yet.

---

## Phase 1 — Agent runs end-to-end (deterministic, placeholder LLM)  🎯
*Goal: `python -m test_data_mining.graph --input data/fixtures --autonomy L1` produces a
report dict, start to finish, with the stub synthesis. This is the spine everything hangs on.*
*(Maps to ROADMAP Milestone 2 + the L1 path of Milestone 5.)*

- [x] `validate` — `validation_ok=False` + gap note when empty; flags insufficient history
      (stays `ok=True` — a valid answer, not a failure); never raises. (`stubs.py`, spec §2.3)
- [x] `suite_health` — pass rate / mean duration / flake rate over the window, unit-tested (G4).
- [x] `coverage_gap` — keeps the honest "no coverage reports (Phase 2)" gap note for the MVP
      (real JaCoCo/lcov parsing is Phase 5+/ROADMAP M2 — not needed for first demo).
- [x] Added `operator.add` reducers on `gaps`/`errors` in `state.py` so degradation notes
      **accumulate** across nodes (and parallel detectors can write them without conflict).
- [x] Run the graph at **L1** end-to-end on fixtures; a full `report` dict comes back.
- [x] 🔒 Confirmed read-only + graceful degradation: missing input dir → `validation_ok=False`,
      3 accumulated gaps, empty report, no crash.
- [x] Unit tests added (`tests/test_validate.py`); full suite 8 passed.

**Done when:** the CLI prints a (placeholder) report from the fixtures without errors at L1. ✅

---

## Phase 2 — Backend API skeleton (FastAPI)  🎯
*Goal: a thin HTTP layer so the agent can be driven by uploaded files or pasted text. No UI
yet — verify with curl / the FastAPI `/docs` page.*
*(New code — suggested home: `backend/app.py`. Reuses `build_graph()` + `initial_state()` verbatim.)*

- [x] Added `fastapi`, `uvicorn[standard]`, `python-multipart` (+ `httpx` for TestClient) to `requirements.txt`.
- [x] `POST /analyse` (`backend/app.py`) — accepts **either** uploaded files **or** pasted
      `text` + `format` (`auto|junit|playwright`) + `autonomy` (`L1|L2|L3`), unified over one
      multipart endpoint (one URL/content-type for the frontend). Plus `GET /health`.
- [x] Materialises input into a temp `data/_uploads/<session>/run_NN/` layout the existing
      `ingest` node reads (one uploaded file = one run; pasted text = one run), then
      `GRAPH.invoke(initial_state(...))` off the event loop via `run_in_threadpool`.
- [x] Returns `report` + `flaky_findings`/`coverage_findings`/`failure_clusters`/`suite_health`
      + accumulated `gaps`/`errors` + `meta`. (FastAPI encodes the dataclasses.)
- [x] 🔒 Untrusted uploads: per-file (10MB) + text + file-count caps, extension allow-list
      (`.xml`/`.json`), client filename discarded (no path traversal), session dir deleted
      after each run. Read-only throughout.
- [x] CORS enabled for the Vite/CRA dev origins (`:5173`, `:3000`).
- [x] Verified: TestClient suite `tests/test_backend.py` (both modes + 4 guard cases) — 15
      tests pass; live `uvicorn` HTTP smoke (`/health` + `/analyse`) returns a report.

**Done when:** uploaded files and pasted text both return a report at L1. ✅
**Run it:** `uvicorn backend.app:app --reload --port 8000` → open `http://localhost:8000/docs`.

---

## Phase 3 — React frontend MVP  🎯
*Goal: the clickable demo loop — upload **or** paste → Analyse → see the report → Download.
Built at L1 first (no review gate) to keep the slice simple.*
*(New code — suggested home: `frontend/` via Vite + React.)*

- [x] Vite + React scaffold in `frontend/` with **Tailwind CSS v3** (PostCSS), component-local state.
- [x] **Input region with two tabs:** *Upload files* (drag-drop / browse, multiple `.xml`/`.json`)
      and *Paste text* (textarea + `auto|junit|playwright` selector). (`InputPanel.jsx`, demo-overview §2.1)
- [x] **Autonomy selector** (L1/L2/L3) in the header (demo defaults to L1; L2 gate is Phase 7).
- [x] **Analyse button** → multipart POST to `/analyse` (`api.js`); disabled until there's input.
- [x] **Report panel** (`ReportView.jsx`) — flaky table (ranked, scored), failure clusters,
      coverage gaps, suite-health stat cards, recommendations; `gaps`/`errors` shown as notices.
- [x] **⬇ Download Report** — client-side blob export: JSON (raw) + Markdown (shareable) (`download.js`).
- [x] Loading / error / empty states.
- [x] Verified: `npm run build` compiles (Tailwind CSS emitted, 35 modules); dev server boots
      and serves the transformed app + components over HTTP. Backend contract matches `api.js`.

**Done when:** in the browser, a non-technical user can upload or paste data, click Analyse,
read the report, and download it — entirely at L1. ✅
**Run it:** terminal 1 `uvicorn backend.app:app --port 8000` · terminal 2 `cd frontend && npm run dev` → open `http://localhost:5173`.

---

## Phase 4 — Live agent-trace panel (streaming)  🎯
*Goal: the "show, don't tell" moment — watch nodes run one by one.*

- [x] Backend: `POST /analyse/stream` emits NDJSON via `GRAPH.stream(stream_mode="updates")` —
      one `{type:"node", node, summary, elapsed_ms, gaps, errors}` per node as it completes,
      then a final `{type:"result", ...}` with the full report (pulled from `get_state`).
- [x] Frontend: **Agent Trace panel** (`TracePanel.jsx`) — ✓ rows pop in node-by-node with
      one-line summary + timing, and a ◐ running pulse while the stream is open. (demo-overview §2.3)
- [x] `gaps`/`errors` shown inline under the node that raised them.
- [x] Client reads the stream with `fetch` + `getReader()` (EventSource can't POST) — `api.js`.
- [x] Verified: TestClient stream tests (node events + result, all nodes present) and a live
      `curl -N` run streaming 8 node events then the result over real HTTP. 17 tests pass.

**Done when:** clicking Analyse animates the trace node-by-node, ending in the report. ✅

---

## Phase 5 — Failure clustering: ChromaDB + LLM labels
*Goal: replace the exact-match placeholder in `failure_clustering` with real semantic
grouping. (ROADMAP Milestone 3, spec §2.6.) 🔒 Vector DB only — no graph DB.*

- [x] Normalise messages/stacks → signature (strip numbers, hex addresses, timestamps,
      UUIDs, `:line:col`, durations). `normalise_signature` in `nodes/failure_clustering.py`.
- [x] Embed signatures (local deterministic signed token-hashing, L2-normalised → **offline**,
      no model download) + greedy cosine clustering in **ChromaDB** (distance ≤ 0.30 ≈ sim ≥ 0.70).
      🔒 Pure-Python cosine fallback if Chroma can't init → graceful degradation, gap noted.
- [x] 🔒 The vector DB *forms* clusters; labelling is separate. Default labels are deterministic
      and grounded in the signature; a **Hub LLM labeler injection seam** (`label_clusters(..., llm=)`)
      is in place — it only *relabels*, never forms clusters. (No standalone key; Hub-routed in prod.)
- [x] Anti-hallucination: `_grounded()` accepts an LLM label only if its salient terms appear
      in the cluster's real messages, else keeps the deterministic label.
- [x] Replaced the exact-match placeholder in `stubs.py`; wired `failure_clustering` into `graph.py`.
- [x] Verified: 5 unit tests (normalise/cluster/label/grounded) + sample data → 3 clusters
      (timeouts, element-not-visible, HTTP-500) with labels. ChromaDB path runs (no fallback). 22 tests pass.

**Done when:** similar-but-not-identical failures group together and clusters carry sane labels. ✅
**Note:** LLM cluster labels are a ready injection seam, not active in this offline demo — the
spec routes them through the Hub LLM router (never a standalone key here). Labels are deterministic
+ grounded today; same anti-hallucination gate applies when the Hub labeler is wired.

---

## Phase 6 — LLM synthesis + persistence
*Goal: a genuinely prioritised, recommendation-bearing report, and a saved record.
(ROADMAP Milestone 4, spec §2.3 G5.)*

- [x] `synthesis` (`nodes/synthesis.py`) — ranks flaky + clusters + coverage + suite-health by
      severity into `priorities`, writes a `summary` + grounded `recommendations`, respects HITL
      `review_decisions` dismissals. Deterministic + reproducible; **Hub LLM narrative seam**
      (`synthesis(state, llm=)`) rewrites only the summary, and only if grounded.
- [x] Anti-hallucination: deterministic recommendations reference only real findings (test ids,
      counts, measured rates); the LLM seam re-checks grounding before accepting any narrative.
- [x] `persist` (`nodes/persist.py`) — writes to **MongoDB** when `MONGODB_URI` is set, else
      dumps JSON to `data/reports/report_<ts>.json`; records `persisted_to`. 🔒 No Neo4j, no
      `KG_SIGNAL_*`. Falls back to a local file (with a gap note) if Mongo is unreachable.
- [x] UI surfaces `summary` + severity-badged `priorities`; Markdown export includes them.
- [x] Verified: 5 synthesis/persist unit tests + end-to-end on sample data (7 findings,
      5 recommendations, JSON persisted). 26 tests pass; frontend builds.

**Done when:** the report has real ranked recommendations and is persisted (locally for the demo). ✅
**Note:** LLM synthesis is a ready seam (Hub-routed in prod, no standalone key here); the offline
default is deterministic + grounded, with the same anti-hallucination gate when the LLM is wired.

---

## Phase 7 — L2 HITL review gate through the UI  🎯
*Goal: the supervised flow — the agent pauses, the analyst confirms/filters, then it continues.
(ROADMAP Milestone 5, spec §2.2.)*

- [x] `review` node (`stubs.py`): `interrupt(findings)` pauses under L2; resume via
      `Command(resume=decisions)` delivers `{dismissed_flaky, dismissed_clusters}` → `review_decisions`.
- [x] Backend: `/analyse/stream` emits an `interrupt` event and stops at the gate; `POST /resume`
      (session + decisions JSON) resumes the same `thread_id` and streams to completion. Shared
      `_stream_events` helper handles node/interrupt/result; `_SESSIONS` keeps meta for the resume.
- [x] Frontend: `ReviewGate.jsx` — at L2 the trace pauses, findings show with keep/dismiss
      checkboxes; **Confirm & continue** posts to `/resume` and the stream resumes into the report.
- [x] 🔒 Conditional routing verified: **L1/L3 skip `review`** (no pause, straight to result);
      **only L2 stops** at the gate. Unknown/expired session → 404.
- [x] Verified: 4 backend tests (pause→resume w/ dismissal honoured, L1 no-pause, 404) + frontend
      build. 29 tests pass.

**Done when:** an L2 run visibly pauses, takes analyst input, and finishes with a filtered report. ✅

---

## Phase 8 — Polish, testing & demo dry-run  🎯
*Goal: it's robust enough to demo live without surprises.*

- [x] Unit tests per finished node: validate, suite_health, failure_clustering, synthesis,
      persist, plus the existing flaky_detect (pattern from `tests/test_flaky_detect.py`).
- [x] Integration tests (`tests/test_integration.py`): full graph at L1 & L3, L2 interrupt→resume
      with dismissal honoured, and missing-input graceful degradation — against the real graph.
- [x] Adversarial tests (`tests/test_adversarial.py`): corrupt XML, malformed JSON, mixed
      formats in one run, single-run insufficient-history, empty dir — all degrade, none crash.
- [x] One-command startup: `scripts/run_demo.ps1` (Windows) + `scripts/run_demo.sh` (unix);
      README "Run the full demo" section. Cosmetic test warnings silenced via `pyproject.toml`.
- [x] Dry-run: the **38-test suite** exercises the full demo loop in-process (upload/paste →
      stream → L2 pause → resume → report → persist). Browser click-through remains a manual step.

**Done when:** the demo script runs start-to-finish on a clean checkout without manual fixups. ✅
**Verified:** `pytest` → 38 passed, 0 warnings; `npm run build` clean.

---

## Suggested target layout after this plan

```
test-data-mining-agent/
├── src/test_data_mining/        # the agent (exists; nodes get finished)
├── backend/                     # FastAPI: /analyse, /resume, trace streaming   [Phase 2,4,7]
├── frontend/                    # React (Vite): upload/paste, trace, report, download [Phase 3+]
├── data/
│   ├── fixtures/  golden/        # exist
│   ├── _uploads/                # temp materialised inputs (gitignored)         [Phase 2]
│   └── reports/                 # local report dumps (gitignored)              [Phase 6]
└── docs/                        # specs + this plan
```

## Fastest path to *a* demo
If you need something to show ASAP, the critical path is **Phase 0 → 1 → 2 → 3**: that yields
a working upload/paste → analyse → report → download loop at L1 using the deterministic
detectors and a placeholder synthesis. Phases 4–7 then make it impressive (live traces, real
clustering, LLM recommendations, the supervised review gate).

---

*References: [`demo-overview.md`](demo-overview.md) (UI + architecture) ·
[`ROADMAP.md`](ROADMAP.md) (agent node checklist) · [`test-data-mining.md`](test-data-mining.md)
(approved spec) · [`CLAUDE.md`](../CLAUDE.md) (working contract & invariants).*
