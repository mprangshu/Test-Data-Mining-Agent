# CLAUDE.md — Test Data Mining Agent (v2)

> Auto-loaded by Claude Code. Single source of truth for how to work on this project.
> **Authoritative design: [`docs/TDM-PIVOT-v2.md`](docs/TDM-PIVOT-v2.md)** — it supersedes the
> original analysis-agent spec (`docs/test-data-mining.md`) and the earlier pivot note. Read the
> pivot doc fully before writing code; this file is the working summary. The build sequence and
> phase status live in [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md).
>
> **⚠ The agent has pivoted.** v1 was a read-only CI-results *analysis* agent (flaky detection,
> failure clustering, quality report) and is **fully built but now retired** — kept in git history
> and referenced by the old spec. We are now building **v2: a test-data *generation* agent.**

---

## What we are building (v2)

An agent that **generates accurate, ready-to-use test data**. It takes **test cases / user
stories** (primary input) **plus** their **JUnit/Playwright result files** (supporting input),
mines existing data from **MongoDB** and similar data from **ChromaDB**, detects **coverage gaps**
from the result files, then **generates new test data** — offering the QA engineer **2–3 candidate
value sets per field** in a human-in-the-loop gate. The chosen sets are assembled into rows,
**downloaded as CSV**, and **optionally saved back to MongoDB** (and upserted to ChromaDB) for reuse.

- **Agent ID:** `test-data-mining` (unchanged)
- **Architecture:** L2 · multi-node LangGraph `StateGraph` (gather → generate → review → synthesise → persist)
- **Autonomy:** L2 · Supervised **only** — the set-selection HITL gate **always runs** (no L1/L3 toggle); the only other human decision is the explicit save gate in `persist`
- **Output:** rows of test data (**CSV**), not a quality report.
- **Language:** Python 3.11+

## The two inputs (the heart of v2)

| Input | Role | Formats | Drives |
|---|---|---|---|
| **Primary — test cases / user stories** | *what fields are needed* | `.xlsx`, `.csv`, `.json`, `.txt` (Gherkin/acceptance) | the field list to generate for |
| **Supporting — test results** | *what was actually tested + real values* | JUnit/TestNG `.xml`, Playwright `.json` | (1) coverage-gap detection, (2) realistic **seed values** from passing runs |

Supporting docs do double duty: **fill gaps** (scenario types never exercised) and **seed realism**
(real values from *passing* runs become few-shot examples for the LLM/generator).

## The five goals (reframed for v2)

| ID | Goal |
|----|------|
| G1 | **Parse fields** — extract required fields, constraints, scenario types from test cases/stories |
| G2 | **Read results** — parse supporting JUnit/Playwright → per-scenario outcomes + seed values |
| G3 | **Mine existing** — MongoDB lookup + ChromaDB similarity for reusable data |
| G4 | **Coverage gaps + generate** — find untested field×scenario combos; generate 2–3 candidate value SETS per field, gap-filling and seeded, all constraint-valid |
| G5 | **Set-based HITL → dataset** — analyst picks one set per field; assemble rows → CSV → optional save-back to MongoDB |

---

## Architecture rules — DO NOT VIOLATE (invariants, pivot §11)

1. **READ-BEFORE-WRITE on MongoDB.** The entire mine phase is read-only. The **only** write is the
   explicit `persist` gate, and **only** when the analyst sets `save=true`.
2. **NO GRAPH DATABASE. NO NEO4J.** Vectors → **ChromaDB**; documents → **MongoDB**. No graph DB
   anywhere. Do not emit `KG_SIGNAL_*` events.
3. **DETERMINISTIC BEFORE LLM.** `parse`, `load_results`, `mongo_lookup`, `vector_search`,
   `coverage_gap` are pure/deterministic and run **before** `generate` (the LLM step).
4. **GRACEFUL DEGRADATION.** Any store unreachable or input malformed → empty result + a `gaps`
   note, **never crash**. No MongoDB data at all → pure-LLM generation path (expected first run).
5. **LLM VIA GEMINI.** LLM use (candidate-set generation, synthesis narrative) goes through
   **Google Gemini** using the `google-genai` SDK, via the seam in `llm.py` (`get_llm()`). The API
   key comes from env **`GEMINI_API_KEY`** (model from `GEMINI_MODEL`, default `gemini-2.5-flash`) —
   **never hard-coded or committed** (use a gitignored `.env`). When no key is set the nodes fall
   back to deterministic, seeded generation, so everything runs offline/in tests without a key.
6. **ANTI-HALLUCINATION.** Every generated value must satisfy the field's `constraints`
   (e.g. currency ∈ ISO-4217, email format) **before** it becomes a candidate set — regenerate on failure.

---

## LangGraph topology (pivot §3)

```
parse → [ load_results | mongo_lookup | vector_search ]  (parallel after parse)
      → coverage_gap → generate → review (HITL set-based, ALWAYS) → synthesise → persist
```

`coverage_gap` depends on `load_results`. `review` **always runs** via `interrupt()` →
`Command(resume=…)` (this agent is L2-only — there is no skip path). `persist` runs only when
the persist gate is `save=true`.

## Node responsibilities (pivot §3 / §10)

| Node | Type | Responsibility |
|------|------|----------------|
| `parse` | deterministic | Extract required fields, constraints, scenario types from the **primary** inputs |
| `load_results` | deterministic | Parse **supporting** JUnit/Playwright → `result_signals` + `seed_values` (passing-run values) |
| `mongo_lookup` | deterministic | Query MongoDB for existing data matching test-case IDs / story keys |
| `vector_search` | vector (ChromaDB) | Embed fields+story; pull top-K similar stored datasets |
| `coverage_gap` | deterministic | `required fields × {valid,boundary,negative,edge}` minus what results exercised |
| `generate` | LLM (seam) | Per field: 2–3 candidate value **sets** (valid / gap-filling / edge), seeded + constraint-valid |
| `review` | HITL (always) | Pause; analyst picks one set per field (or excludes); resume drives synthesise |
| `synthesise` | deterministic + LLM | Assemble final rows from chosen sets; resolve cross-field constraints; write report |
| `persist` | deterministic (gated) | If `save=true`: write dataset to MongoDB + upsert ChromaDB. No Neo4j, no KG signals |

---

## Build order

Follow [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md) (v2 phases). Pivot §12 build order, in short:
`state.py → parse → load_results → generate_fixtures (seed Mongo+Chroma+inputs) → mongo_lookup →
vector_search → coverage_gap → generate → graph → backend (/mine,/resume,/persist) → review →
synthesise → persist → frontend (InputPanel, ReviewGate, ReportView, PersistGate, api, download,
TracePanel) → tests`. Deterministic data-gathering first; LLM `generate`/`synthesise` last.

## File changes vs v1 (pivot §6)

- **Delete:** `nodes/flaky_detect.py`, `nodes/failure_clustering.py`, `nodes/synthesis.py`,
  `nodes/stubs.py`, `scripts/score_golden.py`, `tests/test_flaky_detect.py`, `tests/test_validate.py`.
- **Rewrite:** `state.py` (new schema, pivot §4), `graph.py`, `nodes/persist.py`, `backend/app.py`,
  `scripts/generate_fixtures.py`; split `nodes/ingest.py` → `nodes/parse.py` + `nodes/load_results.py`.
- **Create:** `nodes/{parse,load_results,mongo_lookup,vector_search,coverage_gap,generate,review,synthesise}.py`.
- **Frontend:** new `InputPanel` (two buckets), rewrite `ReviewGate` (per-field radio sets),
  rewrite `ReportView` (CSV + coverage), **new `PersistGate`**, `api.js`/`download.js` (CSV primary).
- **Deps:** add `openpyxl` (xlsx test-case sheets); keep `lxml` (JUnit still parsed as supporting input).

## Canonical data schema

Fixtures and the demo are built around the order-flow schema (pivot §9), columns:
`order_id, customer_name, email, country, currency, payment_method, card_number_masked,
item_count, order_total, coupon_code, order_status, created_at, scenario_tag, data_category`.
A reference `tdm_demo_output.csv` defines this shape. **If that file is not present in the repo,
synthesise one from the column list above** (noted in BUILD-PLAN) so fixtures stay faithful.

---

## Conventions

- **Structured log prefixes:** `NODE_ENTER` / `NODE_EXIT`, `WS_EVENT`, `LLM_CALL` / `LLM_RESP`,
  `NODE_ERROR`. No `KG_SIGNAL_*`.
- **LLM access** via Google Gemini (`google-genai`) through `llm.py` `get_llm()`; key from env
  `GEMINI_API_KEY`. No key → deterministic fallback. Never commit keys (use a gitignored `.env`).
- **Checkpointer:** `MemorySaver` for the MVP (required for `interrupt()`/resume).
- **Parsing:** stdlib `xml.etree` for JUnit; native JSON for Playwright; `openpyxl` for xlsx;
  stdlib `csv` for csv; lightweight Gherkin parse for `.txt`. `lxml` available for richer XML.
- Every node is a pure function `def node(state: AgentState) -> dict:` returning only the keys it
  updates. Keep I/O and LLM calls injected (`node(state, llm=None)`) so nodes stay unit-testable.
- **Reuse v1 plumbing:** LangGraph `interrupt()`/resume, the NDJSON streaming backend, the offline
  deterministic ChromaDB embedder, and the `gaps`/`errors` accumulate-reducers all carry over.

## Commands

```bash
pip install -r requirements.txt
python scripts/generate_fixtures.py          # seed MongoDB(local JSON) + ChromaDB + sample inputs/results
pytest -q
uvicorn backend.app:app --port 8000          # API: /mine, /resume, /persist
# frontend: cd frontend && npm run dev   (or scripts/run_demo.ps1)
```
