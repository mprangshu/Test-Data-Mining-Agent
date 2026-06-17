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
MAX_FILES = 200
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


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ext(name: str) -> str:
    return os.path.splitext(name or "")[1].lower()


def _save_uploads(files: list[UploadFile], dst: str, allowed: set[str]) -> int:
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
    payload = {
        "type": "result",
        "meta": {**meta, "fields": len(state.get("parsed_fields", []))},
        "report": state.get("report"),
        "final_dataset": state.get("final_dataset", []),
        "coverage_gaps": [{"field_name": g.field_name, "scenario_type": g.scenario_type}
                          for g in state.get("coverage_gaps", [])],
        "gaps": state.get("gaps", []),
        "errors": state.get("errors", []),
    }
    return jsonable_encoder(payload)


def _stream_events(graph_input, config: dict, session: str, meta: dict, cleanup_dir: str | None = None):
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
    return {"status": "ok"}


@app.post("/mine")
def mine(
    test_cases: list[UploadFile] = File(default=[]),
    results: list[UploadFile] = File(default=[]),
    text: str | None = Form(None),
    format: str = Form("auto"),
) -> StreamingResponse:
    """Mine inputs and stream the agent trace to the review gate (NDJSON)."""
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
def resume(session: str = Form(...), review_selections: str = Form("[]")) -> StreamingResponse:
    """Resume a paused run with the analyst's set selections; stream to the final result."""
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
