# Test Data Mining Agent — Demo & UI Overview

> **Audience:** Senior / Manager review. **Purpose:** a one-read overview of the
> interactive demo we are building on top of the approved Test Data Mining Agent
> ([`docs/test-data-mining.md`](test-data-mining.md)) — what the user sees, how data
> flows, and how it maps to the existing LangGraph pipeline. This is a *demo* scope:
> a simple, working end-to-end slice for stakeholder walkthroughs, not the production
> Hub integration.

| Field | Value |
|---|---|
| Component | Interactive demo UI + thin API for `test-data-mining` |
| Frontend | **React.js** (single-page, minimal — built for a live demo) |
| Backend | FastAPI thin wrapper around the existing LangGraph agent |
| Autonomy (demo default) | **L2 · Supervised** (review gate shown in UI); L1/L3 toggleable |
| Status | 🟡 Proposed demo build — for approval / direction |
| Invariants | **Read-only · No Neo4j · Deterministic-before-LLM** (unchanged from spec) |

---

## 1. What we are demoing (the elevator pitch)

A QA lead opens a single web page, **drops in their CI test results** (or pastes them
into a text box), clicks **Analyse**, and within seconds sees a prioritised
quality-intelligence report: which tests are flaky, where coverage is thin, which
failures cluster together, and how the suite is trending. They can **watch the agent
work step-by-step** (live agent traces) and **download the full report** as a file to
share or attach to a ticket.

No CI integration, no setup, no credentials — paste or upload, analyse, download. That
is the entire demo loop, and it is enough to show the agent's value in a 5-minute walkthrough.

---

## 2. The UI (React.js, single page)

A deliberately simple layout — one screen, four regions. Built in React.js with plain
component state; no heavy framework so it stays demo-fast and easy to read.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Test Data Mining Agent                            [ Autonomy: L2 ▼ ]      │  ← header
├──────────────────────────────────────────────────────────────────────────┤
│  INPUT                                                                     │
│  ┌────────────────────────────┐   ┌────────────────────────────────────┐  │
│  │  [ Tab: Upload files ]      │   │  [ Tab: Paste text ]               │  │
│  │                             │   │                                    │  │
│  │   ⬆  Drag & drop or browse  │   │   ┌──────────────────────────────┐ │  │
│  │   JUnit .xml / Playwright   │   │   │  paste raw XML / JSON here…  │ │  │
│  │   .json (multiple, multi-   │   │   │                              │ │  │
│  │   run supported)            │   │   └──────────────────────────────┘ │  │
│  │                             │   │   Format: ( auto ▼ )               │  │
│  └────────────────────────────┘   └────────────────────────────────────┘  │
│                                                                            │
│                      [  ▶  Analyse  ]      [ Clear ]                       │
├──────────────────────────────────────────────────────────────────────────┤
│  AGENT TRACE (live)                                                        │
│   ● ingest          parsed 400 results across 10 runs            ✓ 0.4s    │
│   ● validate        validation_ok=true                           ✓ 0.1s    │
│   ● flaky_detect    6 flaky of 40 tests                          ✓ 0.2s    │
│   ● coverage_gap    no coverage reports in input (gap flagged)   ✓ 0.0s    │
│   ● failure_cluster 3 clusters                                   ✓ 0.3s    │
│   ● suite_health    pass_rate 0.92 · flake_rate 0.15            ✓ 0.1s    │
│   ◐ review          ⏸ awaiting analyst confirmation (L2)                   │
│   ○ synthesis       …                                                      │
│   ○ persist         …                                                      │
├──────────────────────────────────────────────────────────────────────────┤
│  REPORT                                          [ ⬇ Download Report ]     │
│   ▸ Flaky tests (ranked)      ▸ Failure clusters                           │
│   ▸ Coverage gaps             ▸ Suite-health trend                         │
│   ▸ Prioritised recommendations                                            │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Input region — two ways to provide data

The defining UX requirement: **the user can either upload files OR paste text**, via two
tabs over the same input area.

| Mode | What it accepts | Notes |
|---|---|---|
| **Upload files** | One or more `.xml` (JUnit/TestNG) and `.json` (Playwright) files; multi-run supported (e.g. several runs for flaky detection) | Drag-and-drop or file browser. Files are read client-side and posted to the API. |
| **Paste text** | Raw XML or JSON pasted directly into a textarea | For the quick case — grab one report, paste, analyse. A small `auto / junit / playwright` format selector resolves ambiguity. |

> **Why both:** uploading suits a real multi-run history (flaky detection needs ≥ N runs);
> pasting suits a fast single-report demo. Same backend path — both end up as normalised
> `TestResult` records through the existing `ingest` node.

### 2.2 Analyse button
A single primary action. Disabled until there is input. On click it posts the payload to
the backend and streams the agent trace back into the **Agent Trace** panel.

### 2.3 Agent Trace panel (live)
A live, node-by-node view of the LangGraph run — one row per node, mirroring the
platform's structured log prefixes (`NODE_ENTER` / `NODE_EXIT` / `NODE_ERROR`). Each row
shows status (pending ○ / running ◐ / done ✓ / error ✗), the node's one-line summary, and
elapsed time. This is the "show, don't tell" moment of the demo — the manager *sees* the
deterministic detectors run before the LLM, and sees the **L2 review gate pause** for human
confirmation.

### 2.4 Report panel + Download button
The synthesised, prioritised report rendered as readable sections (flaky table, cluster
list, coverage gaps, suite-health, recommendations). A prominent **⬇ Download Report**
button exports the full report — **JSON** (machine-readable, the raw agent output) with a
**Markdown** option for pasting into a ticket or wiki. Download is purely client-side from
the already-returned report payload.

---

## 3. Architecture — how the demo wraps the agent

The demo adds **two thin layers** (React UI + a FastAPI endpoint) around the **existing,
unchanged** LangGraph agent. No agent invariant changes; the UI is just a new trigger and
a renderer.

```
┌─────────────────────────────┐         ┌──────────────────────────────────────────────┐
│  React.js single-page UI     │         │  FastAPI demo backend (thin)                   │
│                              │  HTTP   │                                                │
│  • Upload / Paste tabs       │ ──────► │  POST /analyse                                 │
│  • Autonomy selector (L1-L3) │  multi- │    1. write uploaded/pasted data to a temp     │
│  • Analyse button            │  part   │       run dir  (data/_uploads/<session>/…)     │
│  • Live agent-trace panel    │ ◄────── │    2. initial_state(path, autonomy)            │
│  • Report + Download button  │  SSE /  │    3. build_graph().invoke(state)              │
│                              │  stream │    4. stream NODE_ENTER/EXIT events as trace   │
└─────────────────────────────┘         │    5. return final `report` dict               │
                                         │  GET  /resume  (L2 review: Command(resume=…))   │
                                         └───────────────────┬────────────────────────────┘
                                                             ▼
                                  ┌──────────────────────────────────────────────────────┐
                                  │  EXISTING LangGraph agent (unchanged — spec §2.2)       │
                                  │                                                        │
                                  │  ingest → validate →                                   │
                                  │    [ flaky_detect | coverage_gap | failure_clustering ]│
                                  │      → suite_health → (review @L2) → synthesis → persist│
                                  │                                                        │
                                  │  Deterministic detectors first · LLM only labels/      │
                                  │  synthesises · ChromaDB for clustering · NO Neo4j       │
                                  └──────────────────────────────────────────────────────┘
```

### 3.1 Request flow (the demo loop)
1. **User** uploads files or pastes text, picks autonomy (default L2), clicks **Analyse**.
2. **Frontend** posts the payload (multipart for files, JSON body for pasted text) to
   `POST /analyse`.
3. **Backend** materialises the input into a temporary `run_*` directory layout the
   existing `ingest` node already understands, builds the initial `AgentState`, and invokes
   the compiled graph.
4. As each node runs, the backend **streams** its `NODE_ENTER`/`NODE_EXIT` summary back
   (Server-Sent Events or WebSocket) → the **Agent Trace** panel updates live.
5. Under **L2**, the graph hits the `review` interrupt and pauses; the UI surfaces the
   findings for **analyst confirm/filter**, then calls `/resume` with the decisions
   (`Command(resume=…)`).
6. The final `report` dict returns; the **Report** panel renders it and the **Download**
   button is enabled.

### 3.2 Mapping UI ↔ agent state
| UI element | Backed by agent state key |
|---|---|
| Upload / paste input | `input_path` → `raw_results` (via `ingest`) |
| Autonomy selector | `autonomy_level` (L1 / L2 / L3) |
| Flaky table | `flaky_findings` |
| Coverage gaps | `coverage_findings` (+ honest gap note if no coverage data) |
| Failure clusters | `failure_clusters` |
| Suite-health trend | `suite_health` |
| Review gate | `review_decisions` (L2 `interrupt()` / resume) |
| Report + Download | `report` |
| Trace warnings | `gaps` / `errors` (graceful-degradation notes) |

---

## 4. What the demo proves (and what it intentionally defers)

**Proves**
- End-to-end value: raw CI data → prioritised insights in one screen, in seconds.
- The agent's core differentiators are visible: deterministic flaky scoring, failure
  clustering, suite-health trend, and the **L2 human-in-the-loop review gate**.
- Read-only by construction — the UI has no "fix"/"quarantine" action; it only surfaces.
- Both input modes (upload + paste) work against the same normalisation path.

**Defers (out of demo scope — unchanged from the spec roadmap)**
- Real CI/CD trigger (`webhook`/`api`), scheduled nightly runs.
- Coverage at requirement granularity (Phase 2, MongoDB refs — still no graph DB).
- Production persistence to the MongoDB run store (demo can dump report JSON locally).
- Full Hub GenUI component set (demo uses simple React tables/lists as the fallback).
- AuthN/AuthZ, multi-project, history browsing.

---

## 5. Tech & build notes (for the team)

| Concern | Demo choice |
|---|---|
| Frontend | React.js (Vite), single page, component-local state, no Redux — keep it small |
| File handling | Read files client-side; post multipart to `/analyse` |
| Streaming traces | Server-Sent Events (simplest) or WebSocket if we reuse the Hub contract |
| Backend | FastAPI thin wrapper; reuses `build_graph()` and `initial_state()` verbatim |
| LLM access | Hub Python LLM router (Anthropic default) — no standalone key in this repo |
| Vector store | ChromaDB for failure clustering (per spec §2.6) — **no Neo4j anywhere** |
| Persistence | Demo: report JSON to `data/reports/`; Prod: MongoDB run store |
| Download | Client-side blob export — JSON (raw) + Markdown (shareable) |

> **Build order:** the deterministic agent core already works today (ingest +
> flaky_detect score against the golden set at spec targets). The demo work is therefore
> mostly the **two thin layers** — the FastAPI `/analyse` + `/resume` endpoints and the
> React page — plus finishing the stubbed nodes (`coverage_gap`, `failure_clustering`,
> `synthesis`, `persist`) per [`ROADMAP.md`](ROADMAP.md). None of it touches the
> agent's invariants.

---

## 6. Demo script (5 minutes)

1. Open the page. Show the two input tabs.
2. **Upload** the 10-run fixture set (`data/fixtures/run_*`) → click **Analyse**.
3. Narrate the **live trace**: deterministic detectors finish first; the run **pauses at
   the L2 review gate**.
4. Confirm/filter findings → resume → **synthesis** writes the prioritised report.
5. Walk the **report**: ranked flaky tests, failure clusters, suite-health, recommendations.
6. Click **Download Report** → open the file. Done.
7. (Optional) Switch to **Paste text**, drop in a single JUnit XML, re-run to show the
   quick path and the "insufficient history" honesty when there's only one run.

---

*References: approved spec [`docs/test-data-mining.md`](test-data-mining.md) · working
contract [`CLAUDE.md`](../CLAUDE.md) · build checklist [`ROADMAP.md`](ROADMAP.md) ·
data sourcing [`DATA.md`](DATA.md).*
