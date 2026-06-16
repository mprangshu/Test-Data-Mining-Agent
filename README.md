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

# 6. (after building out the LLM/vector nodes) run the full graph
python -m test_data_mining.graph --input data/fixtures --autonomy L2
```

## Project layout

```
test-data-mining-agent/
├── CLAUDE.md                  # Claude Code contract (read first)
├── README.md                  # this file
├── DATA.md                    # data sourcing decision + how to get/generate data
├── ROADMAP.md                 # node-by-node build checklist
├── requirements.txt
├── docs/
│   └── test-data-mining.md    # the approved ADLC spec (source of truth)
├── src/test_data_mining/
│   ├── state.py               # AgentState contract  [DONE]
│   ├── graph.py               # StateGraph wiring + conditional HITL routing
│   └── nodes/
│       ├── ingest.py          # JUnit XML + Playwright JSON parsers  [DONE, working]
│       ├── flaky_detect.py    # deterministic flakiness scoring      [DONE, working]
│       └── stubs.py           # validate / coverage / clustering / review / synthesis / persist  [TODO]
├── scripts/
│   ├── generate_fixtures.py   # synthetic data + golden labels       [DONE, working]
│   └── score_golden.py        # Phase-4 precision/recall harness      [DONE, working]
├── data/
│   ├── fixtures/              # generated test-execution data
│   └── golden/                # ground-truth labels for scoring
└── tests/
    └── test_flaky_detect.py   # starter unit tests                    [DONE]
```

## Current status

The **deterministic core works today**: ingest parses both MVP formats, the flaky detector
scores against ground truth, and the included golden-set run meets the spec targets
(flaky precision ≥ 0.85, recall ≥ 0.75). The vector-clustering and LLM nodes are scaffolded
stubs with spec-anchored TODOs — see `ROADMAP.md` for the build order.

## Hard rules (do not violate)

- **Read-only.** Never disable, quarantine, or rewrite tests; never mutate pipelines.
- **No graph database / no Neo4j.** Clustering uses ChromaDB (vectors); Phase-2 requirement
  linkage uses MongoDB document refs. See spec §2.6.
- **Deterministic detectors before LLM.** The LLM only normalises failure messages, labels
  clusters, and writes the final synthesis — never computes a flakiness score.
