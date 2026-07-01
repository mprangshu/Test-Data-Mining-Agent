"""
app.py — FastAPI wrapper around the Test Data Mining LangGraph agent (v2).

Endpoints (pivot §8):
  * ``POST /mine``   — two file buckets (`test_cases[]`, `results[]`) or pasted `text`; streams the
    agent trace as NDJSON up to the (always-on) review gate, emitting an ``interrupt`` event.
  * ``POST /resume`` — ``session_id`` + ``review_selections`` JSON → continues to the final
    ``result`` (report + final_dataset).
  * ``GET /health``.

The agent is L2-only: every run pauses at the review gate. Uploads are untrusted (size caps,
extension allow-lists per bucket, no path traversal, session cleanup). Read-only mine phase.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from time import perf_counter

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "src"))

from test_data_mining.graph import build_graph                 # noqa: E402
from test_data_mining.state import initial_state               # noqa: E402

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 10 * 1024 * 1024
MAX_FILES = 20
TEST_CASE_EXTS = {".xlsx", ".csv", ".json", ".txt"}
RESULT_EXTS = {".xml", ".json"}
UPLOADS_ROOT = os.path.join(_REPO, "data", "_uploads")

app = FastAPI(title="Test Data Mining Agent — v2 API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"],
)

GRAPH = build_graph()
_SESSIONS: dict[str, dict] = {}   # session → meta (for /resume to rebuild the result payload)
_ROUNDS: dict[str, dict] = {}     # session → latest working state (post-resume / post-generate-more)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ext(name: str) -> str:
    # Extract the file extension (lowercase). Used to validate upload file types.
    return os.path.splitext(name or "")[1].lower()


def _save_uploads(files: list[UploadFile], dst: str, allowed: set[str]) -> int:
    # Save a batch of uploaded files to disk, validating size and extension.
    # Returns the count of successfully saved files. Callers: /mine endpoint.
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (max {MAX_FILES}).")
    saved = 0
    for i, up in enumerate(files):
        if not (up.filename or ""):
            continue
        ext = _ext(up.filename)
        if ext not in allowed:
            raise HTTPException(status_code=422,
                                detail=f"Unsupported file type '{ext or up.filename}'. Allowed: {sorted(allowed)}.")
        content = up.file.read()
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"File '{up.filename}' exceeds {MAX_FILE_BYTES} bytes.")
        os.makedirs(dst, exist_ok=True)
        safe = f"{i}_{os.path.basename(up.filename)}"
        with open(os.path.join(dst, safe), "wb") as fh:
            fh.write(content)
        saved += 1
    return saved


def _save_text(text: str, dst: str, fmt: str) -> None:
    # Save pasted text to disk, auto-detecting format (JSON, Gherkin, or CSV).
    # Output: one file created in `dst` directory. Caller: /mine endpoint.
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=413, detail=f"Pasted text exceeds {MAX_TEXT_BYTES} bytes.")
    fmt = (fmt or "auto").lower()
    head = text.lstrip()[:200].lower()
    if fmt in ("json",) or (fmt == "auto" and head[:1] in ("{", "[")):
        ext = ".json"
    elif fmt in ("txt", "gherkin") or (fmt == "auto" and ("feature" in head or "scenario" in head or head[:1] == "<")):
        ext = ".txt"
    else:
        ext = ".csv"
    os.makedirs(dst, exist_ok=True)
    with open(os.path.join(dst, f"pasted{ext}"), "w", encoding="utf-8") as fh:
        fh.write(text)


def _summarise(node: str, u: dict | None) -> str:
    # Generate a human-readable summary of node outputs for streaming NDJSON events.
    # Output: single-line string (e.g., "5 fields", "12 signals"). Caller: _stream_events.
    u = u or {}
    return {
        "parse": f"{len(u.get('parsed_fields', []))} fields",
        "load_results": f"{len(u.get('result_signals', []))} signals, {len(u.get('seed_values', []))} seeded",
        "mongo_lookup": f"{len(u.get('existing_data', []))} existing dataset(s)",
        "vector_search": f"{len(u.get('retrieved_data', []))} similar case(s)",
        "coverage_gap": f"{len(u.get('coverage_gaps', []))} gaps",
        "generate": f"{len(u.get('candidate_sets', []))} fields with candidate sets",
        "review": "selections applied",
        "synthesise": f"{(u.get('report') or {}).get('row_count', '?')} rows",
        "persist": "persisted",
    }.get(node, "done")


def _result_payload(state: dict, meta: dict) -> dict:
    # Assemble a JSON-serializable result payload from the final graph state.
    # Output example: {"type": "result", "report": {...}, "final_dataset": [...]}.
    # Callers: /resume, /mine (after paused session finishes), /generate-more.
    payload = {
        "type": "result",
        "meta": {**meta, "fields": len(state.get("parsed_fields", []))},
        "report": state.get("report"),
        "final_dataset": state.get("final_dataset", []),            # clean rows (fields only) for CSV
        "output_rows": state.get("output_rows", []),               # rows WITH provenance for the UI
        "coverage_gaps": [{"field_name": g.field_name, "scenario_type": g.scenario_type}
                          for g in state.get("coverage_gaps", [])],
        "gaps": state.get("gaps", []),
        "errors": state.get("errors", []),
    }
    return jsonable_encoder(payload)


def _stream_events(graph_input, config: dict, session: str, meta: dict, cleanup_dir: str | None = None):
    # Generator that streams NDJSON events from the graph as it executes.
    # Yields node updates, then either an interrupt (paused at review) or a final result.
    # Callers: /mine and /resume endpoints. Output: gen() yields NDJSON lines.
    def gen():
        try:
            last = perf_counter()
            interrupted = False
            for chunk in GRAPH.stream(graph_input, config, stream_mode="updates"):
                now = perf_counter()
                if "__interrupt__" in chunk:
                    intr = chunk["__interrupt__"]
                    payload = getattr(intr[0], "value", {}) if intr else {}
                    yield json.dumps({"type": "interrupt", "session": session, "payload": payload}) + "\n"
                    interrupted = True
                    break
                for node, update in (chunk or {}).items():
                    yield json.dumps({
                        "type": "node", "node": node, "status": "done",
                        "summary": _summarise(node, update),
                        "gaps": (update or {}).get("gaps", []),
                        "errors": (update or {}).get("errors", []),
                        "elapsed_ms": round((now - last) * 1000),
                    }) + "\n"
                last = now
            if not interrupted:
                final = GRAPH.get_state(config).values
                _ROUNDS[session] = final          # keep for /persist + the iterative /generate-more loop
                yield json.dumps(_result_payload(final, meta)) + "\n"
                _SESSIONS.pop(session, None)
        finally:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    return gen()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    # Health check endpoint. Always returns 200 OK.
    return {"status": "ok"}


@app.post("/mine")
def mine(
    test_cases: list[UploadFile] = File(default=[]),
    results: list[UploadFile] = File(default=[]),
    text: str | None = Form(None),
    format: str = Form("auto"),
) -> StreamingResponse:
    """Mine inputs and stream the agent trace to the review gate (NDJSON).

    Inputs: test case files/text + optional result files. Saves them to a session dir.
    Output: NDJSON stream of node updates, ends with an "interrupt" event at the review gate.
    """
    session = uuid.uuid4().hex[:12]
    session_dir = os.path.join(UPLOADS_ROOT, session)
    tc_dir = os.path.join(session_dir, "test_cases")
    res_dir = os.path.join(session_dir, "results")
    try:
        n_tc = 0
        if text and text.strip():
            _save_text(text, tc_dir, format)
            n_tc += 1
        n_tc += _save_uploads(test_cases, tc_dir, TEST_CASE_EXTS)
        if n_tc == 0:
            raise HTTPException(status_code=422, detail="Provide test cases (files or pasted text).")
        n_res = _save_uploads(results, res_dir, RESULT_EXTS)
    except Exception:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise

    meta = {"session": session, "test_cases": n_tc, "results": n_res}
    _SESSIONS[session] = meta
    return StreamingResponse(
        _stream_events(initial_state(session_dir), {"configurable": {"thread_id": session}},
                       session, meta, cleanup_dir=session_dir),
        media_type="application/x-ndjson",
    )


@app.post("/resume")
def resume(session: str = Form(...), review_selections: str = Form("")) -> StreamingResponse:
    """Resume a paused run with the analyst's set selections; stream to the final result.

    Inputs: session ID + JSON array of ReviewSelection objects from /mine interrupt.
    Output: NDJSON stream of remaining node updates, ends with final "result" event.
    """
    config = {"configurable": {"thread_id": session}}
    snapshot = GRAPH.get_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=404, detail="No paused run for this session.")
    try:
        selections = json.loads(review_selections or "[]")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="review_selections must be valid JSON.")

    from langgraph.types import Command

    meta = _SESSIONS.get(session, {"session": session})
    return StreamingResponse(
        _stream_events(Command(resume={"review_selections": selections}), config, session, meta),
        media_type="application/x-ndjson",
    )


def _latest_state(session: str) -> dict:
    """The most recent working state for a session: the latest generate-more round if any, else
    the graph checkpoint (post-resume).

    Output: AgentState dict. Callers: /generate-more, /persist use this to get the current dataset.
    """
    if session in _ROUNDS:
        return _ROUNDS[session]
    return GRAPH.get_state({"configurable": {"thread_id": session}}).values


@app.post("/generate-more")
def generate_more(session: str = Form(...), seed_selection: str = Form("")) -> dict:
    """Iterative loop (CONTEXT-v3 §1, Q2=replace): the analyst's picked rows seed a fresh grounded
    round. The selection becomes the new base; everything else is regenerated. Read-only (no save).

    Inputs: session ID + JSON array of row objects from the current dataset.
    Output: new result JSON with updated round_index, report, final_dataset, output_rows.
    """
    state = _latest_state(session)
    if not state or not state.get("final_dataset"):
        raise HTTPException(status_code=404, detail="No generated dataset for this session.")
    try:
        selection = json.loads(seed_selection or "[]")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="seed_selection must be valid JSON.")
    if not isinstance(selection, list) or not selection:
        raise HTTPException(status_code=422, detail="Select at least one row to seed the next round.")

    from test_data_mining.nodes.synthesise import synthesise

    columns = state.get("input_columns") or list(selection[0].keys())
    sel_rows = [{c: r.get(c, "") for c in columns} for r in selection]   # the curated new base

    new_state = dict(state)
    new_state["input_rows"] = sel_rows                  # REPLACE: selection is the new seed/base
    new_state["input_columns"] = columns
    new_state["input_row_count"] = len(sel_rows)
    new_state["round_index"] = int(state.get("round_index", 0)) + 1
    new_state.update(synthesise(new_state))             # deterministic, consistent with the graph path
    _ROUNDS[session] = new_state

    meta = {"session": session, "round": new_state["round_index"],
            "fields": len(new_state.get("parsed_fields", []))}
    return jsonable_encoder({
        "type": "result",
        "meta": meta,
        "round_index": new_state["round_index"],
        "report": new_state.get("report"),
        "final_dataset": new_state.get("final_dataset", []),
        "output_rows": new_state.get("output_rows", []),
        "gaps": new_state.get("gaps", []),
        "errors": new_state.get("errors", []),
    })


@app.post("/persist")
def persist(
    session: str = Form(...),
    save: str = Form("false"),
    label: str = Form("generated_dataset"),
    tags: str = Form(""),
) -> dict:
    """Persist gate: if ``save`` is truthy, write the session's latest dataset to MongoDB + ChromaDB.

    Inputs: session ID, save flag (true/false), label, comma-separated tags.
    Output: {"saved": true/false, "receipt": {...}} from write_dataset or empty.
    """
    state = _latest_state(session)
    final_dataset = state.get("final_dataset") if state else None
    if not final_dataset:
        raise HTTPException(status_code=404, detail="No generated dataset for this session.")
    if str(save).lower() not in ("true", "1", "yes", "on"):
        return {"saved": False}

    from test_data_mining.nodes.persist import write_dataset

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    receipt = write_dataset(final_dataset, label or "generated_dataset", tag_list, state.get("report"))
    return {"saved": True, "receipt": receipt}
