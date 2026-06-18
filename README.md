# Test Data Mining Agent

A **LangGraph** agent that **generates accurate, ready-to-use test data**. It takes **test cases /
user stories** (+ optional **JUnit/Playwright result files**), mines existing data from **MongoDB**
(*fetched*) and similar data from **ChromaDB** (*gathered*), detects **coverage gaps**, and generates
**coherent new rows** at a human-in-the-loop gate. Output = the **original rows (verbatim) + new
rows**, always larger, in the same columns — a clean **CSV**, with optional save-back for reuse.

> **Canonical docs:** [`docs/CONTEXT.md`](docs/CONTEXT.md) (single source of truth) ·
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · [`docs/DATA-FLOW.md`](docs/DATA-FLOW.md) ·
> [`docs/BACKEND.md`](docs/BACKEND.md) · [`docs/UNDERSTANDING.md`](docs/UNDERSTANDING.md) (plain
> English) · [`docs/architecture.svg`](docs/architecture.svg). Working agreement: [`CLAUDE.md`](CLAUDE.md).
> Superseded design notes live in [`docs/archive/`](docs/archive/). *(The retired v1 analysis agent
> is on the `v1` branch.)*

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

Autonomy is **L2 only** — the set-selection review gate always runs; the only other human decision
is the explicit save gate in `persist`. Each output row is tagged by **provenance** (input /
generated / fetched / gathered) for the UI; the CSV is clean (no provenance column).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # (Windows: .\.venv\Scripts\activate)
pip install -r requirements.txt
python scripts/generate_fixtures.py        # seed MongoDB(local JSON) + ChromaDB + sample inputs/results
python scripts/check_embedding_offline.py  # verify all-MiniLM-L6-v2 loads offline (384-dim)
pytest -q                                   # 57 tests
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
field at the review gate, view the colour-coded provenance table, optionally **select rows →
Generate more** (iterate), download the clean **CSV**, then optionally **Save** for reuse.

### Embeddings & LLM (both optional, both run offline)

- **Embeddings:** `all-MiniLM-L6-v2` (384-dim) via `sentence-transformers`, loaded offline from a
  local snapshot (`EMBED_MODEL_PATH`). Falls back to a deterministic hashed embedder if unavailable.
- **LLM:** Google Gemini via the seam in `llm.py`, keyed by env `GEMINI_API_KEY` (model
  `GEMINI_MODEL`, default `gemini-2.5-flash`) in a gitignored `.env`. No key/quota → deterministic
  generation. On a TLS-inspecting network, point `SSL_CERT_FILE` at a CA bundle.

## Project layout

```
test-data-mining-agent/
├── CLAUDE.md · README.md · requirements.txt · tdm_demo_output.csv  (shape reference only)
├── docs/                       # CONTEXT (canonical) · ARCHITECTURE · DATA-FLOW · BACKEND ·
│                               # UNDERSTANDING · architecture.svg · archive/
├── src/test_data_mining/
│   ├── state.py · graph.py · llm.py · embedding.py · inference.py
│   └── nodes/                  # parse · load_results · mongo_lookup · vector_search ·
│                               # coverage_gap · generate · review · synthesise · persist
├── backend/app.py              # FastAPI: /mine /resume /generate-more /persist /health
├── frontend/src/               # React+Tailwind: InputPanel · TracePanel · ReviewGate ·
│                               # ReportView (provenance) · PersistGate
├── scripts/                    # generate_fixtures · check_embedding_offline · measure_similarity · run_demo
├── data/                       # sample_upload/ · sample_mongo/ · sample_chroma/ · golden/
├── models--sentence-transformers--all-MiniLM-L6-v2/   # local embedding model snapshot
└── tests/                      # 57 tests (units · integration · adversarial · coherence ·
                                # provenance · generate_more · embedding · universality e2e)
```

## Invariants (do not violate — full text in [`docs/CONTEXT.md` §2](docs/CONTEXT.md))

1. **Read-before-write on MongoDB** — only `persist` writes, only on `save=true`.
2. **No graph DB / no Neo4j** — vectors → ChromaDB, documents → MongoDB; no `KG_SIGNAL_*`.
3. **Deterministic before LLM** — the gather/analyse nodes are pure.
4. **Graceful degradation** — store down / bad input → `[]` + gap note, never crash.
5. **Schema-agnostic** — output columns == uploaded columns; no hardcoded column names or domain rules.
6. **Additive & ≥ input** — originals verbatim + new rows; always more out than in.
7. **Coherent whole rows · unique ids · provenance UI-only** — see CONTEXT.md.
