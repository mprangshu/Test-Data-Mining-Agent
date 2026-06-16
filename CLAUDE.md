# CLAUDE.md — Test Data Mining Agent

> This file is auto-loaded by Claude Code. It is the single source of truth for how to
> work on this project. Read it fully before writing code. The authoritative design is
> `docs/test-data-mining.md` (the approved ADLC spec) — this file is the working summary.

---

## What we are building

A **read-only, LangGraph-based analysis agent** that mines a project's CI/CD test-execution
data and produces a prioritised quality-intelligence report. It detects flaky tests, surfaces
coverage gaps, clusters recurring failures by root-cause signature, and tracks suite-health
trends. **It never modifies tests or pipelines** — it only surfaces insights.

- **Agent ID:** `test-data-mining`
- **Architecture:** L2 · multi-node LangGraph `StateGraph` (analysis → review → synthesis → persist)
- **Default autonomy:** L2 · Supervised (one human-in-the-loop review gate before persist)
- **Language:** Python 3.11+

## The five goals (from spec §1.2)

| ID | Goal |
|----|------|
| G1 | Flaky-test detection — non-deterministic pass/fail without a code change, ranked by score |
| G2 | Coverage-gap surfacing — modules/requirements with low, missing, or declining coverage |
| G3 | Failure clustering — group failures by root-cause signature (normalised error + stack) |
| G4 | Suite-health trend — pass rate, mean duration, flake rate over a window |
| G5 | Prioritised report — synthesise the above into a ranked, recommendation-bearing report |

---

## Architecture rules — DO NOT VIOLATE

These are hard constraints from the approved spec. Treat them as invariants.

1. **READ-ONLY.** The agent surfaces findings and recommendations. It must never disable,
   quarantine, rewrite, or skip tests, and never mutate a pipeline. No node may perform a
   write to any test or CI system.
2. **NO GRAPH DATABASE. NO NEO4J.** Failure clustering uses a **vector DB (ChromaDB)** +
   cosine similarity. Phase-2 requirement linkage uses **MongoDB** document refs + a shallow
   aggregation (1–2 hop lookup). Do not introduce Neo4j or any graph DB anywhere. Do not emit
   `KG_SIGNAL_*` events — this agent has no knowledge-graph dependency.
3. **Deterministic first, LLM last.** Statistical detectors (flaky, coverage, trend) are pure
   Python and fully reproducible. The LLM is used ONLY for: failure-message normalisation,
   cluster labelling, and final synthesis. Never let an LLM compute a flakiness score.
4. **Graceful degradation.** On malformed/partial data, return partial results with explicit
   gaps flagged — never crash. Use the platform `NODE_ERROR` convention.
5. **Insufficient history is a valid answer.** Flaky detection needs ≥ N runs at the same
   commit/version. With too little history, report `"insufficient_history"` rather than guess.

---

## LangGraph topology (spec §2.2)

```
ingest → validate → [ flaky_detect | coverage_gap | failure_clustering ]  (parallel)
       → review (HITL, L2 only) → synthesis → persist
```

Conditional routing: the `review` node is **skipped under L1/L3** (routes straight to
`synthesis`) and **active under L2** via `interrupt()` → `Command(resume=...)`.

## Node responsibilities (spec §2.3)

| Node | Type | Responsibility |
|------|------|----------------|
| `ingest` | deterministic | Load configured sources, normalise to a common test-result schema |
| `validate` | deterministic | Quality gates; mark insufficient history / corrupt files |
| `flaky_detect` | deterministic | Pass/fail variance per test across same-version runs → score |
| `coverage_gap` | deterministic | MVP: module/file coverage from the report directly |
| `failure_clustering` | vector + LLM | Embed normalised failures → ChromaDB → cosine cluster; LLM labels clusters |
| `review` | human (HITL) | Analyst confirms/filters findings before persistence (L2 only) |
| `synthesis` | LLM | Rank findings, generate prioritised recommendations |
| `persist` | deterministic | Persist report to the run store (MongoDB) |

---

## Build order (do them in this sequence — see ROADMAP.md for the checklist)

Deterministic, independently-testable nodes first; LLM nodes last.

1. `state.py` — the `AgentState` TypedDict (the contract every node reads/writes). **DONE (stub).**
2. `ingest` — JUnit/TestNG XML + Playwright JSON parsers → normalised `TestResult` records.
3. `validate` — schema/quality gates, insufficient-history flag.
4. `flaky_detect` — deterministic flakiness score. **A working reference version is provided.**
5. `coverage_gap` — module/file coverage parsing (JaCoCo/lcov is Phase 2).
6. `failure_clustering` — ChromaDB embed + cluster (LLM labels last).
7. `synthesis` — LLM ranking + recommendations.
8. `persist` — write report to the run store.
9. Wire conditional `review` routing per autonomy level in `graph.py`.

## Data sources (spec §1.3) — MVP marked ✅

| Source | Format | MVP? |
|--------|--------|------|
| JUnit / TestNG reports | XML | ✅ |
| Playwright results | JSON | ✅ |
| Per-test logs | stdout/stderr text | ✅ |
| Pass/fail history | run-over-run series | ✅ |
| Coverage reports (JaCoCo/lcov) | XML / lcov | Phase 2 |
| Test↔requirement linkage | MongoDB refs | Phase 2 |

See `DATA.md` for how to get/generate data. **Use `scripts/generate_fixtures.py` to produce
test data immediately** — it writes JUnit XML + Playwright JSON across multiple runs with a
known-flaky ground-truth set into `data/fixtures/` and `data/golden/`.

---

## Conventions

- **Structured log prefixes** (reuse platform style): `NODE_ENTER` / `NODE_EXIT`,
  `WS_EVENT`, `LLM_CALL` / `LLM_RESP`, `NODE_ERROR`. No `KG_SIGNAL_*`.
- **LLM access** goes through the Hub's Python LLM router (Anthropic default) — never a
  standalone API key in this repo.
- **Checkpointer:** `MemorySaver` for the MVP.
- **Parsing:** stdlib `xml.etree` is fine for the reference parser; `junitparser`/`lxml` are
  listed in requirements for richer parsing if needed. Playwright results are native JSON.
- Every node is a pure function `def node(state: AgentState) -> dict:` returning only the
  state keys it updates. Keep side effects (I/O, LLM calls) explicit and injected where possible
  so nodes stay unit-testable.

## Commands

```bash
# install
pip install -r requirements.txt

# generate test data (no external deps — stdlib only)
python scripts/generate_fixtures.py

# run tests
pytest -q

# (later) run the graph against generated fixtures
python -m test_data_mining.graph --input data/fixtures
```

## Success metrics to hold yourself to (spec §1.5)

Flaky precision ≥ 0.85, flaky recall ≥ 0.75, coverage-gap F1 ≥ 0.80. The golden set in
`data/golden/` is what you score against.
