# TDM-PIVOT-v2.md — Test Data Mining Agent, Respec for Claude Code

> **Read fully before writing code.** This supersedes the previous pivot note. The agent's job
> is now: **take test cases/user stories + their test-result files, mine existing data from
> MongoDB, and generate accurate new test data — letting the QA engineer choose between 2–3
> candidate data sets per field in a HITL gate, then save the chosen dataset back to MongoDB.**
>
> Two design points here go BEYOND the senior's demo-overview doc and are authoritative:
> 1. **Supporting documents** — JUnit XML / Playwright JSON are a second input that drives
>    both coverage-gap detection AND realistic generation (real passing values seed the LLM).
> 2. **Set-based HITL** — the analyst picks **1 of 2–3 full candidate value SETS per field**
>    (generated variants + the existing set), not just a field on/off checkbox.

---

## 1. The pivot in one paragraph

**Old agent:** read JUnit/Playwright results → detect flaky tests, coverage gaps → quality report.

**New agent:** read test cases/user stories (primary input) **plus** their JUnit/Playwright
result files (supporting input) → look up existing test data in MongoDB → retrieve similar data
via ChromaDB → detect coverage gaps from the result files → generate new test data (using real
passing values as realistic seeds, and filling the gaps) → present a HITL table where the QA
engineer **chooses one of several candidate value sets per field** → assemble the final dataset
→ download CSV → optionally save back to MongoDB for reuse.

**Output:** rows of ready-to-use test data (CSV), not a quality report.

---

## 2. The two inputs and how they work together

This is the heart of the change. The agent consumes **two kinds of input at once**:

| Input | Role | Formats | Drives |
|---|---|---|---|
| **Primary — test cases / user stories** | *What fields are needed* | `.xlsx`, `.csv`, `.json`, `.txt` (Gherkin BDD, acceptance criteria, test-case sheets) | The field list to generate data for |
| **Supporting — test results** | *What was actually tested + real values* | JUnit/TestNG `.xml`, Playwright `.json` | Coverage-gap detection + realistic seed values |

**How the supporting docs influence generation (both effects — confirmed):**

1. **Fill gaps.** The result files show which scenarios/fields were actually exercised. Any
   required field or scenario type (valid / boundary / negative / edge) NOT seen in the results
   is a coverage gap — the agent prioritises generating data for those.
2. **Seed realism.** Real values that appear in *passing* test runs are extracted and handed to
   the LLM as few-shot examples, so generated values look like real data (right formats, right
   distributions) instead of generic placeholders.

So a field like `email` that passed in real runs gets generated values shaped like the real
ones; a `negative`-scenario value that was never tested gets flagged as a gap and generated
fresh.

---

## 3. New pipeline — node by node

Old (retire): `ingest → validate → [flaky|coverage|cluster] → suite_health → review → synthesis → persist`

New (build):
```
parse → load_results → mongo_lookup → vector_search → coverage_gap
      → generate → review (HITL, set-based) → synthesise → persist
```

| Node | Type | What it does | Reads | Writes |
|---|---|---|---|---|
| `parse` | deterministic | Extract required fields, constraints, categories from the **primary** test cases/stories | `input_path` | `parsed_fields` |
| `load_results` | deterministic | Parse the **supporting** JUnit XML / Playwright JSON; extract per-scenario outcomes + real field values seen in passing tests | `input_path` | `result_signals`, `seed_values` |
| `mongo_lookup` | deterministic | Query MongoDB for existing test data matching the test-case IDs / story keys | `parsed_fields` | `existing_data` |
| `vector_search` | vector (ChromaDB) | Embed fields + story context; pull top-K similar cases' stored data | `parsed_fields` | `retrieved_data` |
| `coverage_gap` | deterministic | Cross-reference required fields × scenario types (valid/boundary/negative/edge) against `result_signals`; list what's missing | `parsed_fields`, `result_signals` | `coverage_gaps` |
| `generate` | LLM | For each field, produce **2–3 candidate value SETS** (variants), seeded by `seed_values`, prioritising `coverage_gaps`; skip fields fully covered by existing/retrieved unless gaps remain | `parsed_fields`, `coverage_gaps`, `seed_values`, `existing_data`, `retrieved_data` | `candidate_sets` |
| `review` | HITL (L2 interrupt) | Pause; surface per-field **candidate sets** (2–3 generated + existing + retrieved) so the analyst picks ONE set per field (or excludes the field). On resume, the chosen sets drive synthesise | `candidate_sets`, `existing_data`, `retrieved_data` | `review_selections` |
| `synthesise` | deterministic + LLM | Assemble final dataset rows from the chosen set per field; resolve cross-field constraints; write summary report | `review_selections`, all data keys | `final_dataset`, `report` |
| `persist` | deterministic (conditional) | If persist gate `save=true`: write dataset to MongoDB (label + tags) and upsert into ChromaDB for future retrieval | `final_dataset`, `persist_decision` | `persist_receipt` |

`load_results`, `mongo_lookup`, and `vector_search` are independent → they can run in parallel
after `parse`. `coverage_gap` depends on `load_results`. Keep `generate` after all data-gathering.

---

## 4. State schema — full replacement

**Delete `src/test_data_mining/state.py` and replace with this.**

```python
# state.py — AgentState for Test Data Mining Agent (v2)
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Optional, TypedDict
import operator
from typing import Annotated

class AutonomyLevel(str, Enum):
    L1 = "L1"   # auto-select best set per field, auto-persist, no gates
    L2 = "L2"   # set-selection HITL + persist gate (DEFAULT)
    L3 = "L3"   # every node pauses for approval

ScenarioType = Literal["valid", "boundary", "negative", "edge"]

# ── Primary input: parsed test cases ──────────────────────────────────
@dataclass
class ParsedField:
    name: str                          # "email"
    category: str                      # "Identity" | "PII" | "Financial" | ...
    constraints: list[str]             # ["required", "ISO-4217"] etc.
    source_test_ids: list[str]         # which test cases need this field
    scenario_types: list[str]          # which scenarios reference it

# ── Supporting input: signals from result files ───────────────────────
@dataclass
class ResultSignal:
    test_case_id: str
    scenario_tag: str                  # e.g. "typical_order", "missing_email"
    scenario_type: str                 # valid | boundary | negative | edge
    outcome: Literal["passed", "failed", "skipped", "error"]
    fields_exercised: list[str]        # field names this test touched

@dataclass
class SeedValue:
    field_name: str
    example_values: list[Any]          # real values from PASSING runs (few-shot seeds)

# ── Gathered data ─────────────────────────────────────────────────────
@dataclass
class ExistingRecord:
    test_case_id: str
    label: str
    tags: list[str]
    fields: dict[str, list[Any]]       # field → stored values

@dataclass
class RetrievedRecord:
    test_case_id: str
    similarity_score: float
    fields: dict[str, list[Any]]

@dataclass
class CoverageGap:
    field_name: str
    scenario_type: str                 # the scenario that was never exercised
    reason: str                        # "no negative-case value tested for email"

# ── Candidate sets (what generate produces, what HITL chooses from) ───
@dataclass
class CandidateSet:
    set_id: str                        # "gen_A" | "gen_B" | "existing" | "retrieved"
    source: Literal["generated", "existing", "retrieved"]
    values: list[Any]                  # the actual values in this set
    scenario_coverage: list[str]       # which scenario types this set covers
    note: str                          # short rationale ("boundary-heavy variant")

@dataclass
class FieldCandidates:
    field_name: str
    category: str
    sets: list[CandidateSet]           # 2–3 generated + maybe existing + retrieved
    gap_flagged: bool                  # True if this field had a coverage gap

# ── HITL decision (set-level, per field) ──────────────────────────────
@dataclass
class ReviewSelection:
    field_name: str
    include: bool
    chosen_set_id: Optional[str]       # which CandidateSet the analyst kept
    custom_values: Optional[list[Any]] = None   # if analyst typed their own

# ── The graph state ───────────────────────────────────────────────────
class AgentState(TypedDict, total=False):
    input_path: str
    autonomy_level: AutonomyLevel

    parsed_fields: list[ParsedField]            # parse
    result_signals: list[ResultSignal]          # load_results
    seed_values: list[SeedValue]                # load_results
    existing_data: list[ExistingRecord]         # mongo_lookup
    retrieved_data: list[RetrievedRecord]       # vector_search
    coverage_gaps: list[CoverageGap]            # coverage_gap
    candidate_sets: list[FieldCandidates]       # generate

    review_selections: list[ReviewSelection]    # review (HITL)

    final_dataset: list[dict[str, Any]]         # synthesise
    report: Optional[dict[str, Any]]            # synthesise

    persist_decision: Optional[bool]            # /persist
    persist_label: Optional[str]
    persist_tags: Optional[list[str]]
    persist_receipt: Optional[dict[str, Any]]

    gaps: Annotated[list[str], operator.add]    # accumulate across nodes
    errors: Annotated[list[str], operator.add]
```

---

## 5. The HITL review table — set-based selection (confirmed design)

This differs from the senior's doc (which was field on/off). The analyst chooses **which value
set to keep per field**, from 2–3 generated variants plus existing/retrieved where available.

```
REGION 3 · HITL REVIEW — choose a data set for each field
The agent generated multiple candidate sets per field. Pick one per field (or exclude).

┌───────────────┬───────────┬──────────────────────────────────────────────────┬─────────┐
│ Field         │ Category  │ Candidate sets (choose one)                        │ Include │
├───────────────┼───────────┼──────────────────────────────────────────────────┼─────────┤
│ email         │ Identity  │ ( ) Generated A  user0001@example.com, …  valid    │  [✓]    │
│               │           │ ( ) Generated B  bad@, "", a@b  negative/boundary  │         │
│               │           │ (•) Existing     user0001@example.com, …  (Mongo)  │         │
├───────────────┼───────────┼──────────────────────────────────────────────────┼─────────┤
│ order_total   │ Financial │ (•) Generated A  149.99, 58.40, 2899.00  valid     │  [✓]    │
│  ⚠ gap        │           │ ( ) Generated B  0.00, 0.01, 9999999.99  boundary  │         │
│               │           │ ( ) Retrieved    210.75, 88.00  (ChromaDB)         │         │
├───────────────┼───────────┼──────────────────────────────────────────────────┼─────────┤
│ currency      │ Reference │ (•) Generated A  USD, GBP, INR, EUR  valid         │  [✓]    │
│               │           │ ( ) Generated B  XXX, "", US  negative  ⚠ gap-fill │         │
└───────────────┴───────────┴──────────────────────────────────────────────────┴─────────┘
+ Add custom field          [ ▶ Generate Final Dataset ]
```

**Rules:**
- Each field row shows **2–3 candidate sets** as radio buttons (mutually exclusive — pick one).
- Sets come from `FieldCandidates.sets`: typically `Generated A` (valid-leaning),
  `Generated B` (boundary/negative-leaning, gap-filling), plus `Existing` and/or `Retrieved`
  when MongoDB/ChromaDB had data.
- A `⚠ gap` badge marks fields where `coverage_gap` found an untested scenario; the gap-filling
  set is highlighted so the analyst can favour it.
- The `Include` checkbox excludes the whole field if unchecked.
- "+ Add custom field" lets the analyst type a field + values inline.
- "Generate Final Dataset" POSTs `review_selections` (field → chosen_set_id) to `/resume`.

**Interrupt payload** (`review` node → frontend), shape per field:
```json
{
  "fields": [
    {
      "field_name": "email",
      "category": "Identity",
      "gap_flagged": false,
      "sets": [
        {"set_id":"gen_A","source":"generated","values":["user0001@example.com","..."],"scenario_coverage":["valid"],"note":"valid-leaning"},
        {"set_id":"gen_B","source":"generated","values":["bad@","","a@b"],"scenario_coverage":["negative","boundary"],"note":"gap-filling"},
        {"set_id":"existing","source":"existing","values":["user0001@example.com","..."],"scenario_coverage":["valid"],"note":"from MongoDB"}
      ]
    }
  ]
}
```

**Resume payload** (frontend → `/resume`):
```json
{"session_id":"...","review_selections":[
  {"field_name":"email","include":true,"chosen_set_id":"existing"},
  {"field_name":"order_total","include":true,"chosen_set_id":"gen_A"}
]}
```

Under **L1/L3**, `review` is skipped; L1 auto-picks the set with the widest
`scenario_coverage` per field.

---

## 6. File changes — delete / rewrite / create

### Delete (old agent)
```
src/test_data_mining/nodes/flaky_detect.py
src/test_data_mining/nodes/failure_clustering.py
src/test_data_mining/nodes/synthesis.py            (replaced by synthesise.py)
src/test_data_mining/nodes/stubs.py
scripts/score_golden.py
tests/test_flaky_detect.py
tests/test_validate.py
```

### Rewrite from scratch (same path, new content)
```
src/test_data_mining/state.py        (§4)
src/test_data_mining/graph.py        (§3 topology)
src/test_data_mining/nodes/ingest.py → SPLIT into parse.py + load_results.py (delete ingest.py)
src/test_data_mining/nodes/persist.py
backend/app.py                       (/mine, /resume, /persist — §8)
scripts/generate_fixtures.py         (seed MongoDB + ChromaDB + sample inputs — §9)
tests/test_backend.py, test_integration.py, test_adversarial.py  (new pipeline)
```

### Create new node files
```
src/test_data_mining/nodes/parse.py
src/test_data_mining/nodes/load_results.py
src/test_data_mining/nodes/mongo_lookup.py
src/test_data_mining/nodes/vector_search.py
src/test_data_mining/nodes/coverage_gap.py
src/test_data_mining/nodes/generate.py
src/test_data_mining/nodes/review.py
src/test_data_mining/nodes/synthesise.py
```

### Frontend
```
frontend/src/InputPanel.jsx   — two file groups: "Test cases" (.xlsx/.csv/.json/.txt) AND
                                "Test results (optional)" (.xml/.json supporting docs)
frontend/src/TracePanel.jsx   — new node names (§7 mapping)
frontend/src/ReviewGate.jsx   — REWRITE: per-field radio sets (§5)
frontend/src/ReportView.jsx   — REWRITE: CSV-oriented + coverage-gap section
frontend/src/PersistGate.jsx  — NEW: label + tags + Save/Skip
frontend/src/api.js           — endpoints /mine, /resume, /persist
frontend/src/download.js      — CSV primary, JSON secondary
```

### requirements.txt
```diff
- junitparser>=3.1.0        (keep lxml — still parsing JUnit XML as supporting docs)
+ openpyxl>=3.1.0           (xlsx test-case sheets)
  # keep: langgraph, chromadb, pymongo, fastapi, uvicorn, langchain-core, pytest, lxml
```
Note: JUnit XML / Playwright JSON parsing is still needed — but now as *supporting* input in
`load_results.py`, not as the primary pipeline.

---

## 7. Trace panel node-name mapping (frontend)
```
parse · load_results · mongo_lookup · vector_search · coverage_gap · generate · review · synthesise · persist
```
Old names (ingest, validate, flaky_detect, failure_clustering, suite_health) are all removed.

---

## 8. Backend API

**`POST /mine`** — multipart (files) or JSON (pasted text).
- Two file buckets accepted: `test_cases[]` (.xlsx/.csv/.json/.txt) and `results[]` (.xml/.json, optional).
- Materialise into a temp session dir: `test_cases/` and `results/` subfolders the nodes read.
- Stream NDJSON: one `{type:"node",...}` per node, then `{type:"interrupt", payload}` at the
  review gate (L2), then `{type:"result", report, final_dataset}`.
- Guards unchanged: size caps, extension allow-list, session cleanup, read-only.

**`POST /resume`** — `{session_id, review_selections:[...]}` → `Command(resume=...)` → stream to result.

**`POST /persist`** — `{session_id, save, label?, tags?}` → calls `persist` node when `save=true`.

**`GET /health`** — unchanged.

---

## 9. Sample data — seed MongoDB + ChromaDB + inputs

Rewrite `scripts/generate_fixtures.py` to populate everything the demo needs. Base the data on
the **provided sample CSV** (`tdm_demo_output.csv`) — its columns are the canonical order-flow
schema:

```
order_id, customer_name, email, country, currency, payment_method,
card_number_masked, item_count, order_total, coupon_code, order_status,
created_at, scenario_tag, data_category
```

The generator must produce:

1. **MongoDB seed** (`data/sample_mongo/*.json`, or live Mongo if `MONGODB_URI` set) — 2–3
   stored datasets, e.g. `order_flow_v1` (a subset of the CSV's `valid` rows), so `mongo_lookup`
   returns real existing data. Leave some fields/scenarios absent so there's something to generate.
2. **ChromaDB seed** — embed each stored dataset's test-case context so `vector_search` returns
   similar cases. Use offline deterministic embeddings (no model download), same approach as the
   old `failure_clustering` embedder.
3. **Supporting result files** (`data/sample_upload/results/`) — JUnit XML + Playwright JSON for
   the order-flow tests, where the `valid` scenarios pass (these become `seed_values`) and the
   `negative`/`boundary` scenarios are absent or failing (these become `coverage_gaps`).
4. **Primary input files** (`data/sample_upload/test_cases/`):
   - `order_flow_tests.csv` — test-case sheet listing required fields + scenario types
   - `login_flow_tests.txt` — Gherkin BDD scenarios
5. A small **golden expectation** file so a test can assert the agent finds the seeded gaps and
   reuses the seeded MongoDB values.

> Important: design the seed so the demo tells a story — MongoDB covers the `valid` email/
> order_total values (reused), the result files show `negative`/`boundary` scenarios were never
> tested (gaps), and `generate` fills those gaps with realistic, seeded values across 2–3 sets.

---

## 10. Node build guide (key logic)

**parse** — read `test_cases/`; per format: xlsx/csv → headers/columns = fields (+ a
`scenario_type` column if present); json → schema detect; txt → Gherkin `<placeholders>` and
Given/When/Then → fields + scenarios. Output `parsed_fields`. Never crash → `gaps`.

**load_results** — read `results/`; parse JUnit XML (`<testcase>`/`<failure>`) and Playwright
JSON. Produce `result_signals` (per test: scenario, outcome, fields touched) and `seed_values`
(field → real values seen in **passing** tests, for few-shot seeding). If no result files
provided → empty lists + a gap note (generation still works, just unseeded).

**mongo_lookup** — match by test_case_id / story key / field-name overlap. `MONGODB_URI` or
local `data/sample_mongo/`. Empty/unreachable → `existing_data=[]` + gap note (LLM-only path).

**vector_search** — embed parsed fields + story text, query ChromaDB top-K (K=5), threshold
0.70. Empty/unreachable → `retrieved_data=[]` + gap note.

**coverage_gap** — build the matrix `required fields × {valid,boundary,negative,edge}`; subtract
what `result_signals` show as exercised; remainder = `coverage_gaps`. This is the "analyse the
data and see for coverage gaps" step.

**generate** — per field, build **2–3 candidate sets**:
- `gen_A`: valid-leaning values, seeded from `seed_values` (realistic).
- `gen_B`: boundary/negative-leaning, explicitly targeting `coverage_gaps`.
- (optional `gen_C`) edge-leaning.
- Plus pass through `existing`/`retrieved` as their own selectable sets when present.
Skip pure regeneration for fields fully covered with no gaps (but still expose existing/retrieved
as sets). Anti-hallucination: every generated value must satisfy `constraints` (e.g. currency ∈
ISO-4217, email format), regenerate on failure. LLM via Hub router injection seam
(`generate(state, llm=None)`); offline default = deterministic faker-style generation seeded by
real values.

**review** — build the per-field interrupt payload (§5), `interrupt(payload)`, map the resumed
selections to `ReviewSelection`. Skipped at L1/L3.

**synthesise** — for each included field, take the chosen set's values; align fields into rows
by scenario (one row per scenario across fields); resolve cross-field constraints (e.g. a
`negative` row should combine negative values coherently); emit `final_dataset` (rows shaped
like the sample CSV, incl. `scenario_tag` + `data_category`) and a `report` (totals, source
breakdown %, coverage map, gap notes, recommendations).

**persist** — only if `persist_decision`; write dataset + label + tags to MongoDB and upsert
into ChromaDB so the next run can reuse it. Local JSON fallback. No Neo4j, no `KG_SIGNAL_*`.

---

## 11. Invariants (unchanged)

1. **Read-before-write on MongoDB** — read-only through the whole mine phase; the only write is
   the explicit persist gate, only on `save=true`.
2. **Deterministic before LLM** — parse, load_results, mongo_lookup, vector_search, coverage_gap
   all run before `generate` (the LLM step).
3. **No graph DB / no Neo4j** — ChromaDB (vectors) + MongoDB (documents) only.
4. **Graceful degradation** — any store unreachable → empty + gap note, never crash. No MongoDB
   data at all → pure LLM generation path (this is the expected first-run case).
5. **LLM via Hub router** — no standalone keys; injection seams on `generate` and `synthesise`.
6. **Anti-hallucination** — generated values validated against field constraints before they
   become a candidate set.

---

## 12. Build order for Claude Code

```
1  state.py                         (§4)
2  nodes/parse.py
3  nodes/load_results.py            (JUnit XML + Playwright JSON → signals + seeds)
4  scripts/generate_fixtures.py     (seed Mongo + Chroma + sample inputs/results — §9)
5  nodes/mongo_lookup.py
6  nodes/vector_search.py
7  nodes/coverage_gap.py
8  nodes/generate.py                (2–3 candidate sets per field)
9  graph.py                         (wire; parallel data-gather; L1/L3 skip review)
10 backend/app.py                   (/mine, /resume, /persist; two file buckets)
11 nodes/review.py                  (set-based interrupt payload)
12 nodes/synthesise.py
13 nodes/persist.py                 (Mongo write + Chroma upsert)
14 frontend/InputPanel.jsx          (test-cases + results buckets)
15 frontend/ReviewGate.jsx          (per-field radio sets — §5)
16 frontend/ReportView.jsx          (CSV + coverage section)
17 frontend/PersistGate.jsx         (label/tags/save)
18 frontend/api.js, download.js, TracePanel.jsx
19 tests/                           (unit per node; integration full pipeline; adversarial:
                                     empty Mongo, no result files, malformed inputs, no Chroma)
```

**Fastest demo path:** 1→2→3→4→5→6→7→8→9→10→15→16→17→18 gives the full
upload → mine → choose-sets → CSV → save loop at L2.

---

## 13. Demo story (what the seed data should make possible)

1. Upload `order_flow_tests.csv` (test cases) **and** the JUnit/Playwright result files.
2. Trace: `parse` (11 fields) → `load_results` (valid scenarios passed, negatives missing) →
   `mongo_lookup` (existing email/order_total found) → `vector_search` (similar order cases) →
   `coverage_gap` (negative + boundary scenarios untested) → `generate` (2–3 sets per field) →
   ⏸ review.
3. HITL: for `email` keep the **Existing** set; for `order_total` pick **Generated B (boundary)**
   to cover the gap; exclude a field you don't need. Generate Final Dataset.
4. Report: 20 records, source mix (Existing 30% / Generated 60% / Retrieved 10%), coverage map
   shows gaps now filled. Download CSV (matches `tdm_demo_output.csv` shape).
5. Save to MongoDB as `order_flow_v2`. Re-run → `mongo_lookup` now finds it (closes the loop).
6. Edge case to show honesty: run with **no result files** → trace notes "no seed values,
   generation unseeded"; run with **empty MongoDB** → "no existing data, LLM-only generation".

---

*References: senior's demo-overview (new framing) · sample data `tdm_demo_output.csv` (canonical
schema) · existing CLAUDE.md invariants (carry over) · this file supersedes the earlier pivot note.*
