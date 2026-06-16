# Test Data Mining Agent

A read-only, **LangGraph**-based analysis agent that mines a project's CI/CD test-execution
data and produces a prioritised quality-intelligence report. It detects flaky tests, surfaces
coverage gaps, clusters recurring failures by root-cause signature, and tracks suite-health
trends — and it **never modifies tests or pipelines**.

Built following the **ADLC** (Agent Development LifeCycle). The full approved design lives in
[`docs/test-data-mining.md`](docs/test-data-mining.md). If you're using Claude Code on this
repo, read [`CLAUDE.md`](CLAUDE.md) first — it's the working contract.

## What it does (the five goals)

1. **Flaky-test detection** — tests that pass *and* fail at the same commit, ranked by score.
2. **Coverage-gap surfacing** — modules with low / missing / declining coverage.
3. **Failure clustering** — group failures by normalised root-cause signature (vector DB).
4. **Suite-health trend** — pass rate, mean duration, flake rate over a window.
5. **Prioritised report** — a ranked, recommendation-bearing report for a QA lead.

## Quick start

```bash
# 1. (optional) create a virtualenv
python -m venv .venv && source .venv/bin/activate

# 2. install deps
pip install -r requirements.txt

# 3. generate test data — no external services needed (stdlib only)
python scripts/generate_fixtures.py

# 4. run the unit tests
pytest -q

# 5. score the deterministic detector against the golden set
python scripts/score_golden.py

# 6. run the full graph from the CLI
python -m test_data_mining.graph --input data/fixtures --autonomy L1
```

## Run the full demo (web UI)

The interactive demo is a FastAPI backend + a React/Tailwind frontend (see
[`docs/demo-overview.md`](docs/demo-overview.md)).

```powershell
# one-time setup
python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt
cd frontend ; npm install ; cd ..

# launch backend (:8000) + frontend (:5173) in two windows
powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1
```

Or start them manually: `uvicorn backend.app:app --port 8000` and (in `frontend/`) `npm run dev`.
Then open **http://localhost:5173**, switch to the **Upload files** tab, and add the six
`data/sample_upload/run_*.xml` files (two tests are intentionally flaky). Pick **L2** autonomy
to see the human-in-the-loop review gate pause before the report.

## Project layout

```
test-data-mining-agent/
├── CLAUDE.md                  # Claude Code contract (read first)
├── README.md                  # this file
├── requirements.txt
├── docs/
│   ├── test-data-mining.md    # the approved ADLC spec (source of truth)
│   ├── demo-overview.md       # senior overview of the demo UI + architecture
│   ├── BUILD-PLAN.md          # phased build TODO (agent + API + React UI)
│   ├── UNDERSTANDING.md       # plain-language project explainer
│   ├── ROADMAP.md             # node-by-node build checklist
│   └── DATA.md                # data sourcing decision + how to get/generate data
├── src/test_data_mining/
│   ├── state.py               # AgentState contract
│   ├── graph.py               # StateGraph wiring + conditional HITL routing
│   └── nodes/
│       ├── ingest.py          # JUnit XML + Playwright JSON parsers
│       ├── flaky_detect.py    # deterministic flakiness scoring
│       ├── failure_clustering.py  # ChromaDB vector clustering + grounded labels
│       ├── synthesis.py       # ranked findings + grounded recommendations (LLM seam)
│       ├── persist.py         # MongoDB run store / local JSON fallback
│       └── stubs.py           # validate / coverage_gap / suite_health / review
├── backend/
│   └── app.py                 # FastAPI: /analyse, /analyse/stream (trace), /resume (L2 HITL)
├── frontend/                  # React + Vite + Tailwind single-page demo UI
│   └── src/                   # InputPanel · TracePanel · ReviewGate · ReportView
├── scripts/
│   ├── generate_fixtures.py   # synthetic data + golden labels
│   ├── score_golden.py        # precision/recall harness
│   └── run_demo.ps1           # one-command launcher (backend + frontend)
├── data/
│   ├── fixtures/  golden/     # generated data + ground-truth labels
│   └── sample_upload/         # ready-to-upload demo runs (2 flaky tests)
└── tests/                     # unit + integration + adversarial + backend/API
```

## Current status

**The full pipeline and demo work end-to-end.** Deterministic detectors (flaky, suite-health)
meet the spec targets (flaky precision ≥ 0.85, recall ≥ 0.75); failure clustering runs on
ChromaDB (offline, local embeddings); synthesis ranks findings and writes grounded
recommendations; reports persist to MongoDB (or local JSON). The web UI streams a live agent
trace and supports the L2 review gate. The build history is in [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md).

> **LLM note:** per the spec, LLM use (cluster labels, synthesis narrative) is routed through
> the Hub LLM router — never a standalone key in this repo. Those are wired as ready injection
> seams; the offline default is deterministic + grounded, with anti-hallucination checks intact.

## Hard rules (do not violate)

- **Read-only.** Never disable, quarantine, or rewrite tests; never mutate pipelines.
- **No graph database / no Neo4j.** Clustering uses ChromaDB (vectors); Phase-2 requirement
  linkage uses MongoDB document refs. See spec §2.6.
- **Deterministic detectors before LLM.** The LLM only normalises failure messages, labels
  clusters, and writes the final synthesis — never computes a flakiness score.
