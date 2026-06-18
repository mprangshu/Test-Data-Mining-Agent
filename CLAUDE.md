# CLAUDE.md — working agreement

> Auto-loaded by Claude Code. **The canonical context is [`docs/CONTEXT.md`](docs/CONTEXT.md)** —
> read it before writing code. This file is just the short version + the rules that must never break.
> Companions: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/DATA-FLOW.md`](docs/DATA-FLOW.md),
> [`docs/BACKEND.md`](docs/BACKEND.md), [`docs/UNDERSTANDING.md`](docs/UNDERSTANDING.md),
> [`docs/architecture.svg`](docs/architecture.svg). Superseded notes are in `docs/archive/` (not authoritative).

## What this is
A **test-data *generation* agent** (`test-data-mining`). Inputs: test cases / user stories (+ optional
JUnit/Playwright results). It mines MongoDB (**fetched**) + ChromaDB (**gathered**), detects coverage
gaps, generates coherent new rows at a human-in-the-loop gate, and outputs **original rows + new rows**
as a clean CSV. L2 multi-node LangGraph; Python 3.11+ / FastAPI / React.

Pipeline: `parse → load_results → mongo_lookup → vector_search → coverage_gap → generate → review (HITL) → synthesise → persist`

## Invariants — DO NOT VIOLATE (full text in CONTEXT.md §2)
1. **Read-before-write on MongoDB** — only `persist` writes, only when `save=true`.
2. **No graph DB / no Neo4j** — ChromaDB for vectors, MongoDB for docs; no `KG_SIGNAL_*`.
3. **Deterministic before LLM** — parse/load_results/mongo_lookup/vector_search/coverage_gap are pure.
4. **Graceful degradation** — store down / bad input → `[]` + a `gaps` note, never crash.
5. **Schema-agnostic** — output columns == uploaded columns exactly; **never hardcode column names or
   per-domain coherence rules**; relationships are learned from the data at runtime.
6. **Additive, never subtractive** — originals returned verbatim; the agent only adds rows.
7. **Always ≥ input** — `output_rows ≥ input_rows`, every run (soft ~2× target, no hard cap).
8. **Coherent whole rows** — generate whole records (LLM-grounded or clone-and-perturb), never index-zip.
9. **Unique ids** — id columns get fresh ids continuing the observed pattern; never reuse.
10. **Provenance is UI-only** — `source` in `output_rows`; the CSV (`final_dataset`) is clean.
11. **LLM via the seam** — Gemini through `llm.py get_llm()`, key from env `GEMINI_API_KEY`
    (never committed); no key → deterministic fallback.
12. **Embeddings local + offline** — all-MiniLM-L6-v2 via `embedding.py`; deterministic fallback.

## Conventions
- Each node: pure `def node(state, llm=None) -> dict`, returns only updated keys; I/O & LLM injected.
- Logs: `NODE_ENTER`/`NODE_EXIT`, `EMBED_MODEL`/`EMBED_FALLBACK`, `LLM_CALL`/`LLM_RESP`, `NODE_ERROR`.
- Checkpointer `MemorySaver`. Never commit secrets (`.env`, `.certs/` are gitignored).

## Commands
```bash
pip install -r requirements.txt
python scripts/generate_fixtures.py     # seed Mongo(local) + Chroma + sample inputs
pytest -q                                # 57 tests
uvicorn backend.app:app --port 8000      # API: /mine /resume /generate-more /persist /health
# frontend: cd frontend && npm run dev   (or scripts/run_demo.ps1)
```
