# Test Data Mining Agent (v2)

A **LangGraph**-based agent that **generates accurate, ready-to-use test data**. It takes
**test cases / user stories** plus their **JUnit/Playwright result files**, mines existing data
from **MongoDB** and similar data from **ChromaDB**, detects **coverage gaps**, then generates
**2–3 candidate value sets per field**. A QA engineer picks one set per field in a
human-in-the-loop gate; the chosen sets are assembled into rows, **downloaded as CSV**, and
**optionally saved back to MongoDB** (and upserted to ChromaDB) for reuse.

> Authoritative design: [`docs/TDM-PIVOT-v2.md`](docs/TDM-PIVOT-v2.md). Working contract:
> [`CLAUDE.md`](CLAUDE.md). Build history & status: [`docs/BUILD-PLAN.md`](docs/BUILD-PLAN.md).
> *(v1 was a read-only CI-results analysis agent — preserved on the `v1` branch.)*

## The two inputs

| Input | Role | Formats |
|---|---|---|
| **Test cases / user stories** (primary) | what fields are needed | `.xlsx`, `.csv`, `.json`, `.txt` (Gherkin) |
| **Test results** (supporting, optional) | coverage gaps + realistic seed values | JUnit/TestNG `.xml`, Playwright `.json` |

## Pipeline

```
parse → load_results → mongo_lookup → vector_search → coverage_gap
      → generate → review (HITL, ALWAYS) → synthesise → persist
```

Autonomy is **L2 only** — the set-selection review gate always runs. The only other human
decision is the explicit save gate in `persist`.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # (Windows: .\.venv\Scripts\activate)
pip install -r requirements.txt
python scripts/generate_fixtures.py        # seed MongoDB(local JSON) + ChromaDB + sample inputs/results
pytest -q
python -m test_data_mining.graph --input data/sample_upload   # CLI: runs to the gate, auto-resumes
```

## Run the full demo (web UI)

```powershell
# one-time setup
python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt
python scripts\generate_fixtures.py
cd frontend ; npm install ; cd ..

# launch backend (:8000) + frontend (:5173)
powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1
```

Or manually: `uvicorn backend.app:app --port 8000` and (in `frontend/`) `npm run dev`. Open
**http://localhost:5173**, add the seeded **Test cases** (`data/sample_upload/test_cases/`) and
**Test results** (`data/sample_upload/results/`), click **Mine & Generate**, pick a value set per
field at the review gate, download the **CSV**, then optionally **Save** the dataset for reuse.

### LLM (optional)

Generation/synthesis use **Google Gemini** via the seam in `llm.py`, keyed by env
`GEMINI_API_KEY` (model `GEMINI_MODEL`, default `gemini-2.5-flash`) — set in a gitignored `.env`.
With no key (or no quota) the agent falls back to **deterministic, seeded** generation, so it
runs fully offline. On a TLS-inspecting corporate network, point `SSL_CERT_FILE` at a CA bundle.

## Project layout

```
test-data-mining-agent/
├── CLAUDE.md · README.md · requirements.txt · tdm_demo_output.csv  (canonical schema)
├── docs/                       # TDM-PIVOT-v2 (authoritative) · BUILD-PLAN · demo-overview · …
├── src/test_data_mining/
│   ├── state.py · graph.py · llm.py · embedding.py
│   └── nodes/                  # parse · load_results · mongo_lookup · vector_search ·
│                               # coverage_gap · generate · review · synthesise · persist
├── backend/app.py              # FastAPI: /mine (stream→gate), /resume, /persist, /health
├── frontend/src/               # React+Tailwind: InputPanel · TracePanel · ReviewGate ·
│                               # ReportView · PersistGate
├── scripts/                    # generate_fixtures.py · run_demo.ps1 / .sh
├── data/
│   ├── sample_upload/          # test_cases/ + results/  (seeded demo inputs)
│   ├── sample_mongo/           # local MongoDB seed (reuse loop)
│   └── sample_chroma/          # local ChromaDB store (gitignored)
└── tests/                      # parse · load_results · mongo_lookup · vector_search ·
                                # coverage_gap · generate · persist · backend · integration · adversarial
```

## Invariants (do not violate)

1. **Read-before-write on MongoDB** — the mine phase is read-only; the only write is the explicit
   `persist` save gate (`save=true`).
2. **No graph DB / no Neo4j** — vectors → ChromaDB, documents → MongoDB. No `KG_SIGNAL_*` events.
3. **Deterministic before LLM** — `parse`/`load_results`/`mongo_lookup`/`vector_search`/`coverage_gap`
   run before the LLM `generate` step.
4. **Graceful degradation** — any store unreachable or input malformed → empty result + a gap note,
   never a crash (no Mongo data → pure-LLM generation path).
5. **LLM via Gemini** — env key only, deterministic fallback; **anti-hallucination**: every
   generated value is validated against the field's constraints before it becomes a candidate.
