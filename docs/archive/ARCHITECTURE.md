# Test Data Mining Agent — Architecture & Node Reference

> A read-only LangGraph pipeline that mines CI/CD test-execution data and surfaces quality insights.
> See `architecture.svg` for the visual flow. This document explains every node, the state it reads, and the state it writes.

---

## Pipeline at a glance

```
CI/CD files  ──►  ingest  ──►  validate  ──►  ┌─ flaky_detect      ─┐
                                               ├─ coverage_gap      ─┤  (parallel)
                                               └─ failure_clustering ─┘
                                                         │
                                                   suite_health
                                                         │
                                          ┌──── L2 ─── review (HITL)
                                          │
                                       synthesis  ◄──── L1 / L3 (skip review)
                                          │
                                       persist  ──►  MongoDB report
```

**Three types of node in this pipeline:**

| Type | Colour in diagram | Behaviour |
|---|---|---|
| Deterministic | Teal | Pure Python — same input always gives same output |
| Parallel analysis | Purple | Three nodes that run at the same time |
| LLM-assisted | Coral | Uses the language model for language tasks only |
| Human gate | Amber | Pauses for a person before continuing |

---

## The shared state

Every node reads from and writes to a single shared dictionary called `AgentState` (defined in `state.py`). Think of it as a form that gets filled in section by section.

Key fields, in order of population:

| Field | Type | Populated by |
|---|---|---|
| `input_path` | `str` | Caller (set at startup) |
| `autonomy_level` | `L1 / L2 / L3` | Caller |
| `raw_results` | `list[TestResult]` | `ingest` |
| `validation_ok` | `bool` | `validate` |
| `flaky_findings` | `list[FlakyFinding]` | `flaky_detect` |
| `coverage_findings` | `list[CoverageFinding]` | `coverage_gap` |
| `failure_clusters` | `list[FailureCluster]` | `failure_clustering` |
| `suite_health` | `SuiteHealth` | `suite_health` |
| `review_decisions` | `dict` | `review` (HITL) |
| `report` | `dict` | `synthesis` |
| `gaps` | `list[str]` | Any node (graceful degradation notes) |

---

## Node reference

---

### `ingest`
**Type:** Deterministic  
**File:** `nodes/ingest.py`  
**Status:** ✅ Working

**What it does:**  
Opens every result file in the configured `input_path`, detects the format (JUnit XML or Playwright JSON), parses it, and converts everything into a uniform list of `TestResult` records. Each record carries: test name, suite, pass/fail/skip/error outcome, duration, run ID, commit SHA, timestamp, and the raw error message + stack trace if it failed.

**Why it matters:**  
Different CI tools produce completely different file formats. This node is the "Rosetta Stone" — everything downstream sees one consistent structure regardless of what fed in.

**Reads from state:** `input_path`  
**Writes to state:** `raw_results`, `gaps`  

**Graceful degradation:** A malformed file is logged in `gaps` and skipped. The node never raises — it returns whatever it managed to parse.

**Data sources (MVP):**

| Format | What it parses |
|---|---|
| JUnit / TestNG XML | `<testsuite>` / `<testcase>` / `<failure>` / `<error>` elements |
| Playwright JSON | `suites[].specs[].tests[].results[]` structure |

---

### `validate`
**Type:** Deterministic  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Stub (basic version working)

**What it does:**  
Runs quality gates on the normalised data before any analysis begins. Checks that results are not empty, flags tests that don't have enough run history for reliable flaky detection, and marks the state as valid or invalid. If data is partially corrupt, it notes the gaps and continues — it does not stop the pipeline.

**Reads from state:** `raw_results`  
**Writes to state:** `validation_ok`, `gaps`  

**Key rule:** Never crash. Partial data with honest gap notes is always better than an error. This is a hard constraint from the spec (§1.4 — graceful degradation).

---

### `flaky_detect`
**Type:** Deterministic (parallel)  
**File:** `nodes/flaky_detect.py`  
**Status:** ✅ Working — meets spec targets (precision ≥ 0.85, recall ≥ 0.75)

**What it does:**  
For each test, it groups all its outcomes across runs at the same commit SHA and computes a **flakiness score** — a number from 0 (perfectly stable) to 1 (fails exactly half the time). A test is labelled **flaky** when it has *both* passing and failing outcomes, the minority outcome appears at least twice (to rule out a one-off infra blip), and the score crosses the configured cutoff.

**The three verdicts:**

| Verdict | Meaning |
|---|---|
| `flaky` | Both outcomes seen, minority ≥ 2 appearances, score ≥ cutoff |
| `stable` | Only one outcome, or minority appeared only once |
| `insufficient_history` | Fewer than `min_runs_for_flaky` observations |

**Important:** A test that fails on *every* run is NOT flaky — it's a real regression. The detector keeps these separate. This is the most common trap in naive flaky detection.

**Flakiness score formula:**
```
score = 1 - |passes - fails| / (passes + fails)
```
A 50/50 split scores 1.0 (maximally flaky). A 7-pass / 1-fail scores 0.25 (borderline).

**Reads from state:** `raw_results`, `min_runs_for_flaky`, `flaky_score_cutoff`, `min_minority_fails`  
**Writes to state:** `flaky_findings`

---

### `coverage_gap`
**Type:** Deterministic (parallel)  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Stub (Phase 2)

**What it does:**  
Parses coverage reports to find modules and files with low, missing, or declining test coverage. In the MVP it reads directly from coverage report files (JaCoCo XML or lcov format). If no coverage report is present in the input, it returns an empty list and records an honest gap note — it does not fail.

**Phase 2 extension:** Requirement-level coverage gaps via MongoDB `requirement_id` references on test records (a shallow 1–2 hop lookup — no graph database).

**Reads from state:** `input_path`  
**Writes to state:** `coverage_findings`, `gaps`

---

### `failure_clustering`
**Type:** Vector DB + LLM-assisted (parallel)  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Placeholder (exact-match grouping until ChromaDB is wired)

**What it does — two distinct steps:**

**Step 1 — Vector DB forms the clusters (pure maths, no LLM):**  
Takes every failure message and stack trace, strips the parts that change each run (line numbers, timestamps, memory addresses), and produces a normalised signature. These signatures are converted to embedding vectors and stored in ChromaDB. ChromaDB then groups them by cosine similarity — failures that "mean the same thing" cluster together even if the exact wording differs.

**Step 2 — LLM labels each cluster (language task):**  
The LLM reads the representative failure from each cluster and writes a short human-readable label like "Database connection timeout — affects checkout flow". It can optionally use past resolved failures (RAG) to ground the label. This is the only part where an LLM is involved.

**Why not just use string matching?**  
Two stack traces for the same bug rarely look identical — different line numbers, different call paths from different test setups. Embedding + cosine similarity groups them correctly even with surface variation.

**Why not a graph database?**  
Grouping similar failures is a *semantic similarity* problem, which is exactly what a vector database solves. A graph database is for relationship traversal (multi-hop chains). They are different tools for different problems.

**Reads from state:** `raw_results`  
**Writes to state:** `failure_clusters`

---

### `suite_health`
**Type:** Deterministic  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Stub (basic version in place)

**What it does:**  
Computes the four headline numbers for the test suite over the configured window of runs:

| Metric | How it's calculated |
|---|---|
| Pass rate | passed outcomes / total outcomes |
| Mean duration | average test execution time in seconds |
| Flake rate | flaky tests / total distinct tests |
| Window runs | number of distinct run IDs in the data |

**Reads from state:** `raw_results`, `flaky_findings`  
**Writes to state:** `suite_health`

---

### `review`  *(L2 only)*
**Type:** Human-in-the-loop (HITL)  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Stub (LangGraph `interrupt()` to be wired)

**What it does:**  
Pauses the pipeline and presents the draft findings (flaky tests, coverage gaps, failure clusters) to the QA lead. The analyst can confirm items, dismiss false alarms, or adjust priorities. When they submit, the pipeline resumes with the filtered findings.

**When it runs:** Only under **L2 (Supervised)** autonomy. Under L1 or L3, the conditional edge in `graph.py` routes straight to `synthesis`, skipping this node entirely.

**Implementation mechanism:** LangGraph's `interrupt()` function saves the current state as a checkpoint and suspends. When the analyst submits their review, `Command(resume=...)` re-hydrates the state and continues.

**Reads from state:** `flaky_findings`, `coverage_findings`, `failure_clusters`  
**Writes to state:** `review_decisions`

---

### `synthesis`
**Type:** LLM  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Stub (LLM router to be wired)

**What it does:**  
Takes all confirmed findings and asks the LLM (via the Hub's Python LLM router — Anthropic default) to rank them by severity and write prioritised, human-readable recommendations. Output is a structured report dictionary.

**The LLM's job here is language, not computation.** It does not recalculate flakiness scores or re-cluster failures — it takes the already-computed, already-reviewed findings and writes the prose. Every LLM-claimed root cause is verified against the raw data before being included (anti-hallucination check).

**Reads from state:** `flaky_findings`, `coverage_findings`, `failure_clusters`, `suite_health`, `review_decisions`  
**Writes to state:** `report`

---

### `persist`
**Type:** Deterministic  
**File:** `nodes/stubs.py`  
**Status:** 🔧 Stub (MongoDB write to be wired)

**What it does:**  
Writes the final `report` dictionary to the MongoDB run store so it can be displayed in the Hub workspace and kept for historical comparison. No other writes happen anywhere in the pipeline — this is the only node that touches a database.

**Hard rule:** No Neo4j. No `KG_SIGNAL_*` events. MongoDB only.

**Reads from state:** `report`  
**Writes to state:** *(nothing — side-effect only)*

---

## The two databases

| Database | Used for | Why this one |
|---|---|---|
| **ChromaDB** | Storing and querying failure-signature embeddings (clustering) | Designed for vector similarity search — exactly what clustering needs |
| **MongoDB** | Persisting the final report | Already in the platform; document format fits the report structure naturally |

Neither is a graph database. The spec explicitly rules out Neo4j because the agent has no deep relationship traversal requirements — clustering is a similarity problem (vector DB), and requirement linkage is a shallow 1–2 hop lookup (MongoDB aggregation).

---

## Autonomy levels

| Level | Review gate | Use when |
|---|---|---|
| **L1 — Assistive** | Skipped | Quick checks; low-stakes pipelines |
| **L2 — Supervised** (default) | Active — analyst reviews before persist | Normal use |
| **L3 — Goal-driven** | Skipped | Trusted, mature pipelines; nightly automated runs |

The only code difference is a single conditional edge in `graph.py` that routes either through `review` or directly to `synthesis`.

---

## What "read-only" means in practice

The agent reads files and databases. It writes exactly one thing: the final report to MongoDB via the `persist` node. It never:
- Disables, quarantines, or skips a test
- Modifies a CI pipeline configuration
- Pushes changes to any repository
- Writes to ChromaDB during a production run (embeddings may be cached, but that is infrastructure, not agent action)

This is a hard constraint from the spec (§1.4) and is the foundation of the trust model with QA leads.
