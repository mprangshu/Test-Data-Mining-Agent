# Agent Spec: Test Data Mining Agent

> **🟡 PROPOSAL — awaiting senior approval.** This document follows the ADLC
> (Agent Development LifeCycle) and the QE&A Agentic Hub agent-spec house style.
> It is a *proposal-depth* design: enough to evaluate and approve, not a final
> implementation spec. Full Pydantic models, WebSocket event sequences, and tool
> signatures will be added after sign-off (see `docs/agents/test-case-generation.md`
> for the post-approval template depth).

| Field | Value |
|---|---|
| Agent ID | `test-data-mining` |
| Category | Analysis / Quality Intelligence |
| Status | 🟡 Proposed — awaiting approval |
| Python class | `agents.test_data_mining.TestDataMiningAgent` (proposed) |
| Architecture | L2 · Multi-node LangGraph pipeline (analysis → review → synthesis) |
| Framework | LangGraph (`StateGraph`) + LangChain core |
| **Autonomy Level** | **L2 · Supervised** (default) — L1 and L3 supported — see `docs/agents/frameworks/autonomy-levels.md` |
| **Guardrails** | pii-detection, output-schema-validation — see `docs/agents/frameworks/guardrails.md` |
| **Supported Triggers** | `manual`, `schedule`, `api`, `webhook` — see `docs/agents/frameworks/triggers.md` |

---

## Executive Summary (for approval)

QA teams generate large volumes of CI/CD test-execution data on every run — JUnit/TestNG
reports, Playwright results, per-test logs, pass/fail history, and coverage reports — but
almost none of it is mined systematically. **Flaky tests, coverage gaps, and recurring
failure clusters stay invisible until they cause release pain.** Manual analysis is slow,
inconsistent, and does not scale past a handful of suites.

The **Test Data Mining Agent** is a read-only, LangGraph-based analysis agent that ingests
a project's test-execution data, detects flaky tests, surfaces coverage gaps, clusters
recurring failures by root-cause signature, and produces a prioritised, human-readable
quality-intelligence report rendered in the Hub workspace. It **never modifies tests or
pipelines** — it surfaces insights and recommendations for a QA lead to act on.

**Why now / why this fits the Hub:** it reuses the platform's existing seams — FastAPI
agent runtime, WebSocket streaming, GenUI output components, ChromaDB for failure-similarity
clustering, MongoDB for any requirement↔test linkage, and per-project archetype config for
autonomy and triggers. **It introduces no graph database (no Neo4j).** It complements rather
than overlaps existing agents (see §Boundaries).

**Decision requested:** approval to proceed to a piloted MVP on 1–2 projects, scoped to the
data sources and autonomy level proposed below.

---

## Phase 1 — Problem Definition

### 1.1 Problem statement
Test-execution data accumulates run-over-run across CI/CD pipelines but is not analysed in
aggregate. As a result: flaky tests erode trust in the suite, coverage silently regresses,
and the same failure recurs across builds without anyone connecting the dots. QA leads lack
a fast, repeatable way to turn raw test logs into prioritised, actionable quality signals.

### 1.2 Goals & objectives
| # | Objective | Definition |
|---|---|---|
| G1 | **Flaky-test detection** | Identify tests that pass *and* fail non-deterministically without an intervening code change, ranked by flakiness score |
| G2 | **Coverage-gap surfacing** | Find modules / requirements with low, missing, or declining coverage |
| G3 | **Failure clustering** | Group failures across runs by root-cause signature (normalised error message + stack) |
| G4 | **Suite-health trend** | Quantify pass rate, mean duration, and flake rate over a time window |
| G5 | **Prioritised report** | Synthesise the above into a ranked, recommendation-bearing report for a QA lead |

### 1.3 Data source inventory
| Source | Format | MVP? | Notes |
|---|---|---|---|
| JUnit / TestNG reports | XML | ✅ | Most common CI output; primary MVP source |
| Playwright results | JSON | ✅ | Aligns with Hub's existing Playwright agents |
| Per-test logs | stdout/stderr text | ✅ | Used for failure clustering |
| Pass/fail history | run-over-run series | ✅ | Required for flaky detection (needs ≥ N runs) |
| Coverage reports | JaCoCo XML / lcov | ➖ Phase 2 | Enables G2 at module granularity |
| Test↔requirement linkage (MongoDB) | document refs | ➖ Phase 2 | `requirement_id` references on test records for requirement-level gaps — shallow lookup, no graph DB |

### 1.4 Constraints & assumptions
- **Read-only authority boundary** — the agent surfaces findings and recommendations; it
  never disables, quarantines, or rewrites tests, and never mutates pipelines.
- **Format variance** — CI log formats differ; an adapter/normalisation layer is required.
- **Flaky detection needs history** — at least *N* runs at the same commit/version; with a
  single run the agent reports "insufficient history" rather than guessing.
- **Graceful degradation** — on malformed or partial data the agent returns partial results
  with explicit gaps flagged, never a crash (consistent with platform `NODE_ERROR` handling).
- **Fuzzy outputs** — clustering and synthesis are probabilistic; statistical detectors
  (flaky, coverage) are deterministic and independently verifiable.

### 1.5 Success metrics
| Metric | Target (MVP) | How measured |
|---|---|---|
| Flaky-detection precision | ≥ 0.85 | Against a human-labelled golden set |
| Flaky-detection recall | ≥ 0.75 | Against the same golden set |
| Coverage-gap F1 | ≥ 0.80 | Against known-gap fixtures |
| Time-to-insight | ↓ ≥ 70% vs. manual | Pilot timing study |
| Adoption | ≥ 60% of reports actioned | QA-lead feedback in pilot |

---

## Phase 2 — Agent Design

### 2.1 Architecture & autonomy
L2 · Supervised multi-node LangGraph pipeline. Deterministic detectors run first; an LLM is
used only for failure-message normalisation, cluster labelling, and final synthesis. One HITL
checkpoint lets the analyst review and filter findings before the report is persisted.

| Level | Behaviour | Status |
|---|---|---|
| L1 · Assistive | One-shot: ingest → detect → single report, no review gate | Supported |
| **L2 · Supervised** | **Full pipeline + HITL review of findings before persist** | **Default** |
| L3 · Goal-driven | Full pipeline runs autonomously, persists without review | Supported |

### 2.2 LangGraph topology (proposed)

```
        ┌─────────────┐
        │  ingest     │  load + normalise logs from configured sources
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │  validate   │  schema/quality checks; flag corrupt or insufficient data
        └──────┬──────┘
               ▼
   ┌───────────┼────────────────────┐
   ▼           ▼                     ▼
┌────────┐ ┌──────────┐      ┌────────────────┐
│ flaky  │ │ coverage │      │ failure        │   (parallel analysis)
│ detect │ │ gap      │      │ clustering     │
└────┬───┘ └────┬─────┘      └───────┬────────┘
     └──────────┼────────────────────┘
                ▼
        ┌─────────────────┐
        │  [HITL: review]  │  analyst reviews/filters findings  (L2 only)
        └────────┬────────┘
                 ▼
        ┌─────────────┐
        │  synthesis  │  LLM ranks findings + writes recommendations
        └──────┬──────┘
               ▼
        ┌─────────────┐
        │  persist    │  save report to the run store (MongoDB)
        └─────────────┘
```

**Conditional routing:** the `[HITL: review]` node is skipped under L1/L3 (routes straight to
`synthesis`) and active under L2 via `interrupt()` → `Command(resume=...)`.

### 2.3 Node responsibilities
| Node | Type | Responsibility |
|---|---|---|
| `ingest` | deterministic | Load configured sources, normalise to a common test-result schema |
| `validate` | deterministic | Quality gates; mark insufficient history / corrupt files |
| `flaky_detect` | deterministic | Pass/fail variance per test across same-version runs → flakiness score |
| `coverage_gap` | deterministic | MVP: module/file coverage straight from the report. Phase 2: requirement-level via MongoDB `requirement_id` lookup |
| `failure_clustering` | vector + LLM-assisted | Embed normalised failure messages into a **vector DB (ChromaDB)**, cluster by cosine similarity (threshold / HDBSCAN); LLM labels each cluster, optionally RAG-grounded on past resolved failures. **No graph DB involved** — see §2.6 |
| `review` (HITL) | human | Analyst confirms/filters findings before persistence (L2) |
| `synthesis` | LLM | Rank findings, generate prioritised recommendations |
| `persist` | deterministic | Persist the report to the run store (MongoDB) |

### 2.4 Outputs (GenUI components, proposed)
| Component | Content |
|---|---|
| `flaky-test-table` | Ranked flaky tests with flakiness score, run count, last failure |
| `coverage-heatmap` | Module/requirement coverage with gap highlighting |
| `failure-cluster-list` | Failure clusters with signature, count, representative trace |
| `suite-health-trend` | Pass rate / duration / flake rate over the window |

All four fall back to `MarkdownFallback` via the GenUI registry if not yet implemented.

### 2.5 Tooling (proposed categories)
- **Ingestion adapters** — JUnit/TestNG XML parser, Playwright JSON parser, (Phase 2: JaCoCo/lcov)
- **Analysis** — flaky statistics (deterministic), coverage diff (deterministic), failure embedding + **vector-DB clustering**
- **Vector store** — ChromaDB for failure-signature embeddings + similarity search (already in the platform stack)
- **Linkage (Phase 2)** — MongoDB `requirement_id` lookup for test↔requirement gaps (shallow join, **no graph DB**)
- **Persistence** — report write to the run store (MongoDB)

### 2.6 Design decision — fully Neo4j-free architecture

**Decision:** this agent uses **no graph database**. Failure clustering runs on a **vector
database (ChromaDB) + optional RAG**; the Phase-2 requirement linkage runs on the platform's
**existing document store (MongoDB)**. Neo4j is not a dependency of any node.

**Rationale — clustering:** grouping failures is a **semantic-similarity** problem (embed
normalised error messages → cosine distance → group the near-ones), which is precisely what a
vector DB does — not a graph problem.

**Rationale — requirement linkage (the only thing that looked "graph-shaped"):** the
test → user-story → requirement chain is a **shallow 1–2 hop lookup**, not deep multi-hop
traversal. A relational/document join answers *"which requirements have no linked passing
test?"* with a single aggregation. A graph DB would be over-engineering for that depth, and it
would add a whole datastore (Neo4j) the agent otherwise never needs. We therefore store the
linkage as explicit `requirement_id` / `user_story_id` references on test records in MongoDB
(the platform's primary store) and resolve gaps with an aggregation query.

| Concern | Tool | Why |
|---|---|---|
| Group similar failures (`failure_clustering`) | **ChromaDB** (vector) | Embedding + cosine similarity is a vector operation |
| Label / explain a cluster from past fixes | **RAG** (retrieve resolved failures → ground the LLM) | Prevents hallucinated root causes in `synthesis` |
| Module-level coverage gaps (MVP) | **Coverage report itself** (JaCoCo/lcov) | Per-file coverage is in the report — no linkage store needed |
| Requirement-level coverage gaps (Phase 2) | **MongoDB** (document refs + aggregation) | Shallow 1–2 hop lookup — a join, not a graph traversal |

Note that *clustering* (unsupervised grouping) and *RAG* (retrieval to ground an LLM) are
related but distinct: the vector DB **forms** the clusters; RAG **labels** them. Both stores
the agent uses — ChromaDB and MongoDB — **already exist in the platform** (ChromaDB backs the
agent-recommender; MongoDB backs all CRUD), so **no new infrastructure** is introduced and
**no Neo4j** is required anywhere in the pipeline.

---

## Phase 3 — Development

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Orchestration | LangGraph `StateGraph` + LangChain core |
| LLM access | Via the Hub's Python LLM router (Anthropic default) — **not** a standalone key |
| Parsing | `junitparser` / `lxml`; Playwright JSON native |
| Embedding / clustering | **ChromaDB** (vector DB) for failure-signature embeddings + similarity clustering — see §2.6 |
| Requirement linkage (Phase 2) | **MongoDB** document refs + aggregation — shallow lookup, **no graph DB** |
| Persistence | **MongoDB** run store for the report — no Neo4j, no KG signals |
| Checkpointer | `MemorySaver` for MVP (matches existing agents) |
| Runtime home | `backend-ai/app/agents/test_data_mining/` (FastAPI service) |
| Streaming | Existing WebSocket trace/genui/hitl event contract |
| Config | Per-project archetype (`agent_autonomy_config`, `agent_guardrail_config`, `agent_trigger_config`) |

**Build approach:** node-by-node against the existing agent scaffolding, deterministic
detectors first (independently testable), LLM nodes last. Reuse the platform's structured
log prefixes (`NODE_ENTER`/`NODE_EXIT`, `WS_EVENT`, `LLM_CALL`/`LLM_RESP`). This agent emits
no `KG_SIGNAL_*` events — it has no knowledge-graph dependency.

---

## Phase 4 — Testing & Validation

| Layer | Scope | Method |
|---|---|---|
| **Unit** | Per-node logic | pytest + mocked inputs; fixture JUnit XML / Playwright JSON; hand-calculated flaky scores to assert the deterministic detector |
| **Integration** | Full graph state flow | Edge routing per autonomy level; HITL `interrupt()`/resume; partial-data degradation path |
| **Behavioral / accuracy** | Output quality | Golden set of labelled flaky tests + known coverage gaps → precision/recall/F1; LangSmith tracing; cluster-label spot-checks |
| **Adversarial / edge** | Robustness | Corrupt/empty XML, single-run (no history), huge log volumes (load), missing coverage data, mixed formats |

**Determinism strategy:** statistical detectors run at temperature 0 / pure Python (fully
reproducible); LLM synthesis and cluster labelling are probabilistic and validated by
golden-set scoring + human spot-check rather than exact-match.

---

## Phase 5 — Deployment

- **Runtime:** FastAPI agent in `backend-ai` (Python service owns agent execution).
- **Triggers:**
  - `manual` — analyst runs it against a project in the workspace (MVP).
  - `schedule` — nightly run after CI completes (Celery Beat — see Build step 28).
  - `api` / `webhook` — post-CI-run trigger from the pipeline (Phase 2).
- **Rollout:** pilot on 1–2 projects → validate against golden set → GA.
- **Config:** autonomy level, guardrails, and triggers set per project via the archetype
  schema (no code change to onboard a new project).

---

## Phase 6 — Monitoring & Evaluation

| Pillar | What we watch |
|---|---|
| **Operational** | Run health, duration, cost-per-run (synthesis/clustering token usage), SLA adherence |
| **Output quality** | Benchmark regression vs. golden set, human spot-checks of clusters, run-over-run consistency |
| **Data drift** | Schema drift (new CI format), distribution drift (failure-rate shift), volume/nullity drift |
| **LLM behaviour** | Token usage, cluster-label hallucination rate, synthesis reasoning coherence, refusal rate |
| **Feedback triggers** | Threshold alerts (e.g. precision drop) + HITL corrections feed back into the golden set → periodic re-tune |

Monitoring closes the loop: precision regressions and analyst corrections flow back into
Phase 1 success metrics and the Phase 4 golden set, making the ADLC a true cycle.

---

## Boundaries vs. existing agents

| Agent | Difference |
|---|---|
| `data-coverage` | Generates *combinatorial coverage matrices* for new test design. This agent *mines existing execution data* for gaps and flakiness — analysis, not generation. |
| `defect-triaging` | Triages a *single defect* to root cause + owner. This agent operates on the *aggregate* test corpus to find patterns across many runs. |
| `test-data-provisioning` | Provisions *input data* for test execution. This agent mines *output data* (results/logs) from execution. |

---

## Open questions for senior (decisions needed before MVP)

1. **Data sources in scope for MVP** — confirm JUnit XML + Playwright JSON only, or include
   coverage (JaCoCo/lcov) from day one?
2. **CI/CD systems** — which pipelines feed us (Jenkins, GitHub Actions, Azure DevOps)? Affects ingestion adapters.
3. **Requirement-level gaps in v1?** — MVP does module/file-level coverage straight from the
   report (no linkage store). Pulling requirement-level gaps into v1 means populating
   `requirement_id` references in MongoDB. Defer to Phase 2, or do it now? *(Either way, no
   graph DB — §2.6.)*
4. **Default autonomy** — confirm L2 (review gate) as default, with L1/L3 available.
5. **Flaky threshold** — minimum run count *N* and flakiness-score cutoff for "flaky".
6. **Golden set ownership** — who curates the labelled flaky/coverage golden dataset for Phase 4?

---

## Phase-2 extensions (out of MVP scope)

- Coverage mining at requirement granularity via MongoDB `requirement_id` references (no graph DB).
- Auto-quarantine *recommendations* (still human-actioned) routed to defect-triaging.
- Cross-project flakiness benchmarking (org-wide quality intelligence).
- `webhook`/`api` post-CI triggering and scheduled nightly mining at scale.
- Trend forecasting (predict coverage regression before it ships).
