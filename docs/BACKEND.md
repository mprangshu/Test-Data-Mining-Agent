# BACKEND.md — FastAPI surface, sessions & contracts

> Companion to [`CONTEXT.md`](CONTEXT.md). The backend (`backend/app.py`) is a thin FastAPI wrapper
> around the LangGraph agent: it streams the trace to the HITL gate, resumes with the analyst's
> selections, runs the iterative loop, and saves on the explicit gate. Mine phase is read-only.

---

## Structure (`backend/app.py`)

- `GRAPH = build_graph()` — compiled LangGraph with `MemorySaver`; thread_id = **session**.
- `_SESSIONS: dict` — per-session upload meta (for the result payload).
- `_ROUNDS: dict` — per-session **latest working state** (post-resume / post-generate-more); powers
  `/generate-more` and `/persist`.
- `_stream_events(...)` — shared NDJSON generator: streams `{type:node}` events; on `interrupt`
  emits `{type:interrupt, session, payload}` and stops; otherwise emits `{type:result, …}` and
  stores the final state in `_ROUNDS`.
- `_result_payload(state, meta)` — builds the result (clean `final_dataset` + `output_rows` with
  provenance + report + coverage_gaps + gaps/errors); `jsonable_encoder` serialises the dataclasses.
- Upload guards: `MAX_FILE_BYTES` 10 MB, `MAX_FILES` 200, per-bucket extension allow-lists
  (`TEST_CASE_EXTS = {.xlsx,.csv,.json,.txt}`, `RESULT_EXTS = {.xml,.json}`), session dir cleanup,
  no path traversal. CORS limited to localhost dev origins.

---

## Endpoints

### `POST /mine`  → `StreamingResponse` (NDJSON)
Form fields: `test_cases[]` (files), `results[]` (files, optional), `text` (pasted, optional),
`format`. Creates a session, saves uploads, streams node events up to the review gate.
**Emits:** `{type:"node", node, status, summary, gaps, errors, elapsed_ms}` per node, then
`{type:"interrupt", session, payload}` where `payload.fields[]` lists each field's candidate sets.
422 if no test cases / bad extension.

### `POST /resume`  → `StreamingResponse` (NDJSON)
Form: `session`, `review_selections` (JSON list of `{field_name, include, chosen_set_id,
custom_values?}`). Resumes via `Command(resume=…)`; streams to the final result.
**Emits:** node events, then `{type:"result", meta, report, final_dataset, output_rows,
coverage_gaps, gaps, errors}`. 404 if no paused run for the session.

### `POST /generate-more`  → JSON
Form: `session`, `seed_selection` (JSON list of row field-objects the analyst picked). The selection
becomes the new base (`input_rows`); `round_index += 1`; `synthesise` regenerates everything else
grounded on it — **replace** semantics. Read-only (no Mongo write).
**Returns:** `{type:"result", meta, round_index, report, final_dataset, output_rows, gaps, errors}`.
422 if the selection is empty; 404 if no dataset for the session.

### `POST /persist`  → JSON
Form: `session`, `save` (truthy?), `label`, `tags` (comma-separated). If `save` is truthy, writes
the **latest** dataset (`_latest_state`) to MongoDB + upserts ChromaDB via `write_dataset`.
**Returns:** `{saved:true, receipt:{label, rows, fields, location, chroma_indexed, gaps}}` or
`{saved:false}`. 404 if no dataset.

### `GET /health` → `{status:"ok"}`

---

## Event & row contracts

```jsonc
// node event (stream)
{ "type":"node", "node":"generate", "status":"done", "summary":"13 fields…",
  "gaps":[], "errors":[], "elapsed_ms":42 }

// interrupt event (stream) — the review gate
{ "type":"interrupt", "session":"ab12…",
  "payload": { "fields": [ { "field_name":"email", "category":"Identity",
    "gap_flagged":true, "sets":[ {"set_id":"gen_A","source":"generated",
    "values":["…"],"scenario_coverage":["valid"],"note":"…"}, … ] } ] } }

// result (stream for /resume; JSON for /generate-more)
{ "type":"result", "meta":{"session","fields"}, "round_index":1,
  "report": { "row_count", "input_row_count", "generated_row_count", "columns",
              "provenance":{"input":20,"generated":20,"fetched":10,"gathered":10},
              "scenario_mix", "gaps_filled_fields", "recommendations":[…] },
  "final_dataset": [ {<original columns only>} ],          // clean — for CSV
  "output_rows":  [ {"fields":{…}, "source":"generated", "row_uid":"r0-g3"} ],  // UI provenance
  "coverage_gaps":[…], "gaps":[…], "errors":[…] }
```

`final_dataset` is the clean export (no `source`/`row_uid`); `output_rows` carries provenance for the
UI. The frontend's `downloadCsv` builds the sheet from `final_dataset` only.

---

## Sessions & rounds

- A **session** = a LangGraph thread_id, created by `/mine`. The checkpoint persists across
  `/resume`, `/generate-more`, `/persist`.
- `_ROUNDS[session]` holds the latest working state. `/resume` populates it; `/generate-more`
  replaces it each round (round 0 → 1 → 2 …); `/persist` saves it.
- The agent runs **deterministic** through the graph (the LLM seam isn't wired graph-wide);
  `/generate-more` matches that (`llm=None`) for consistency and test-safety.

---

## Frontend client (`frontend/src/api.js`)

`mine(...)` / `resume(...)` stream NDJSON via `consumeNdjson`; `generateMore(session, rows)` and
`persistDataset(session, {save,label,tags})` are plain JSON POSTs. `API_BASE` from
`VITE_API_BASE` (default `http://localhost:8000`). Components: `InputPanel` (two buckets),
`TracePanel`, `ReviewGate` (per-field radios), `ReportView` (provenance table + filter + select +
generate-more), `PersistGate`. CSV/JSON export in `download.js` (`downloadCsv` clean,
`downloadCsvWithSources` debug).
