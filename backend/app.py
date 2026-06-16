"""
app.py — Thin FastAPI wrapper around the Test Data Mining LangGraph agent (BUILD-PLAN Phase 2).

It exposes ONE analysis endpoint that accepts the agent's input two ways (demo-overview §2.1):
  * uploaded files  — one or more JUnit/TestNG .xml or Playwright .json files, and
  * pasted text     — a single raw XML/JSON blob in a form field.

Both arrive as multipart/form-data so the frontend has a single URL and content type. The
endpoint materialises the input into the ``run_*`` directory layout the existing ``ingest``
node already understands, invokes the compiled graph verbatim, and returns the report plus
the raw findings and any graceful-degradation gaps.

Run:  uvicorn backend.app:app --reload --port 8000   (then open http://localhost:8000/docs)

INVARIANTS (CLAUDE.md): read-only · no Neo4j · deterministic-before-LLM. This layer only
*reads* uploaded data and *reads* the agent's output — it never mutates a test or pipeline.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from time import perf_counter

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# Make src/ importable without installing the package (mirrors scripts/).
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "src"))

from test_data_mining.graph import build_graph                      # noqa: E402
from test_data_mining.state import AutonomyLevel, initial_state     # noqa: E402

# --------------------------------------------------------------------------- #
# Limits — treat all uploads as untrusted (Phase 2 security checklist).
# --------------------------------------------------------------------------- #
MAX_FILE_BYTES = 10 * 1024 * 1024     # 10 MB per file
MAX_TEXT_BYTES = 10 * 1024 * 1024     # 10 MB pasted
MAX_FILES = 200                       # at most N runs per analysis
ALLOWED_EXTS = {".xml", ".json"}
UPLOADS_ROOT = os.path.join(_REPO, "data", "_uploads")

app = FastAPI(title="Test Data Mining Agent — Demo API", version="0.1.0")

# CORS for the local React dev server (Vite default port 5173; CRA 3000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compile the graph once and reuse it (each request uses a unique thread_id).
GRAPH = build_graph()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ext_for_format(fmt: str, text: str) -> str:
    """Resolve a file extension for pasted text from the format hint (or by sniffing)."""
    fmt = (fmt or "auto").lower()
    if fmt in ("junit", "testng", "xml"):
        return ".xml"
    if fmt in ("playwright", "json"):
        return ".json"
    # auto: sniff the first non-space character.
    head = text.lstrip()[:1]
    if head == "<":
        return ".xml"
    if head in ("{", "["):
        return ".json"
    raise HTTPException(status_code=422,
                        detail="Could not detect format of pasted text; choose junit or playwright.")


def _materialise_files(session_dir: str, files: list[UploadFile]) -> int:
    """Write each uploaded file as its own run_NN (one file = one CI run). Returns run count."""
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (max {MAX_FILES}).")
    # Deterministic run ordering by client-provided filename.
    ordered = sorted(files, key=lambda f: f.filename or "")
    n = 0
    for i, up in enumerate(ordered):
        ext = os.path.splitext(up.filename or "")[1].lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(status_code=422,
                                detail=f"Unsupported file type '{ext or up.filename}'. "
                                       f"Allowed: {sorted(ALLOWED_EXTS)}.")
        content = up.file.read()
        if len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413,
                                detail=f"File '{up.filename}' exceeds {MAX_FILE_BYTES} bytes.")
        # Ignore the client path entirely (no traversal); write a fixed name + safe extension.
        run_dir = os.path.join(session_dir, f"run_{i:02d}")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, f"results{ext}"), "wb") as fh:
            fh.write(content)
        n += 1
    return n


def _materialise_text(session_dir: str, text: str, fmt: str) -> int:
    """Write a single pasted blob as run_00. Returns run count (1)."""
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=413, detail=f"Pasted text exceeds {MAX_TEXT_BYTES} bytes.")
    ext = _ext_for_format(fmt, text)
    run_dir = os.path.join(session_dir, "run_00")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, f"results{ext}"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return 1


def _prepare_session(autonomy: str, fmt: str, text: str | None, files: list[UploadFile]):
    """Validate inputs and materialise them into a temp run dir. Shared by both endpoints.

    Returns (level, session, session_dir, n_runs, source). Raises HTTPException on bad input
    (and cleans up the partial session dir before re-raising materialisation errors).
    """
    try:
        level = AutonomyLevel(autonomy.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail="autonomy must be one of L1, L2, L3.")

    has_files = bool(files) and any((f.filename or "") for f in files)
    has_text = bool(text and text.strip())
    if has_files == has_text:  # both or neither
        raise HTTPException(status_code=422,
                            detail="Provide exactly one of: files (upload) or text (paste).")

    session = uuid.uuid4().hex[:12]
    session_dir = os.path.join(UPLOADS_ROOT, session)
    os.makedirs(session_dir, exist_ok=True)
    try:
        n_runs = (_materialise_files(session_dir, files) if has_files
                  else _materialise_text(session_dir, text, fmt))
    except Exception:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise
    return level, session, session_dir, n_runs, ("files" if has_files else "text")


def _summarise(node: str, update: dict | None) -> str:
    """One-line NODE_EXIT-style summary for the live trace, derived from the node's update."""
    u = update or {}
    if node == "ingest":
        return f"parsed {len(u.get('raw_results', []))} results"
    if node == "validate":
        return f"validation_ok={u.get('validation_ok')}"
    if node == "flaky_detect":
        ff = u.get("flaky_findings", [])
        n = sum(1 for f in ff if getattr(f, "verdict", None) == "flaky")
        return f"{n} flaky of {len(ff)} tests"
    if node == "coverage_gap":
        cf = u.get("coverage_findings", [])
        return f"{len(cf)} coverage findings" if cf else "no coverage data"
    if node == "failure_clustering":
        return f"{len(u.get('failure_clusters', []))} clusters"
    if node == "suite_health":
        h = u.get("suite_health")
        return f"pass_rate {h.pass_rate}" if h else "no data"
    if node == "review":
        return "findings reviewed"
    if node == "synthesis":
        return "report assembled"
    if node == "persist":
        return "report persisted"
    return "done"


def _response_from_state(state: dict, meta: dict) -> dict:
    """Shape the final graph state into the API response (FastAPI encodes dataclasses)."""
    return {
        "meta": meta,
        "validation_ok": state.get("validation_ok"),
        "suite_health": state.get("suite_health"),
        "flaky_findings": state.get("flaky_findings", []),
        "coverage_findings": state.get("coverage_findings", []),
        "failure_clusters": state.get("failure_clusters", []),
        "report": state.get("report"),
        "gaps": state.get("gaps", []),
        "errors": state.get("errors", []),
    }


# In-memory map of paused L2 sessions → their meta, so /resume can rebuild the final payload.
# (MemorySaver already holds the graph state per thread_id; this only carries display meta.)
_SESSIONS: dict[str, dict] = {}


def _stream_events(graph_input, config: dict, session: str, meta: dict, cleanup_dir: str | None = None):
    """Shared NDJSON generator for both /analyse/stream and /resume.

    Emits a ``node`` event per completed node; if the graph pauses at an ``interrupt()`` it
    emits an ``interrupt`` event (with the findings) and stops; otherwise it emits the final
    ``result`` event. Cleans up ``cleanup_dir`` when the stream ends (incl. on pause).
    """
    def gen():
        try:
            last = perf_counter()
            interrupted = False
            for chunk in GRAPH.stream(graph_input, config, stream_mode="updates"):
                now = perf_counter()
                if "__interrupt__" in chunk:                       # L2 review gate hit
                    intr = chunk["__interrupt__"]
                    findings = getattr(intr[0], "value", {}) if intr else {}
                    yield json.dumps({"type": "interrupt", "session": session,
                                      "findings": findings}) + "\n"
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
                payload = _response_from_state(final, {**meta, "results_parsed": len(final.get("raw_results", []))})
                payload["type"] = "result"
                yield json.dumps(jsonable_encoder(payload)) + "\n"
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


@app.post("/analyse")
async def analyse(
    autonomy: str = Form("L1"),
    format: str = Form("auto"),
    text: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """Analyse uploaded files OR pasted text and return the quality-intelligence report.

    Provide exactly one of: ``files`` (multipart) or ``text`` (form field). Each uploaded
    file is treated as one CI run; pasted text is treated as a single run.
    """
    level, session, session_dir, n_runs, source = _prepare_session(autonomy, format, text, files)
    try:
        state = initial_state(session_dir, autonomy_level=level)
        config = {"configurable": {"thread_id": session}}
        # Graph invoke is synchronous + CPU-bound — run off the event loop.
        result = await run_in_threadpool(GRAPH.invoke, state, config)
        meta = {
            "session": session, "autonomy": level.value, "source": source,
            "runs": n_runs, "results_parsed": len(result.get("raw_results", [])),
        }
        return _response_from_state(result, meta)
    finally:
        # Read-only + tidy: drop the temp input once analysed (it is gitignored anyway).
        shutil.rmtree(session_dir, ignore_errors=True)


@app.post("/analyse/stream")
def analyse_stream(
    autonomy: str = Form("L1"),
    format: str = Form("auto"),
    text: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
) -> StreamingResponse:
    """Same as /analyse, but streams the agent trace as newline-delimited JSON (NDJSON).

    Emits one ``{"type":"node", ...}`` event per node as it completes (with a one-line summary,
    elapsed time, and any gaps/errors that node raised), then a final ``{"type":"result", ...}``
    event carrying the full report. Bad-input errors are returned as normal 4xx JSON because
    validation/materialisation happen before streaming begins.
    """
    level, session, session_dir, n_runs, source = _prepare_session(autonomy, format, text, files)
    meta = {"session": session, "autonomy": level.value, "source": source, "runs": n_runs}
    _SESSIONS[session] = meta   # kept for /resume to rebuild the final meta after an L2 pause

    state = initial_state(session_dir, autonomy_level=level)
    config = {"configurable": {"thread_id": session}}
    return StreamingResponse(
        _stream_events(state, config, session, meta, cleanup_dir=session_dir),
        media_type="application/x-ndjson",
    )


@app.post("/resume")
def resume(session: str = Form(...), decisions: str = Form("{}")) -> StreamingResponse:
    """Resume an L2 run paused at the review gate, delivering the analyst's filter choices.

    ``decisions`` is a JSON object: ``{"dismissed_flaky": [...], "dismissed_clusters": [...]}``.
    Streams the remaining node events (review → synthesis → persist) and the final result.
    """
    config = {"configurable": {"thread_id": session}}
    snapshot = GRAPH.get_state(config)
    if not snapshot.next:
        raise HTTPException(status_code=404,
                            detail="No paused run for this session (it may have completed or expired).")
    try:
        parsed = json.loads(decisions or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="decisions must be valid JSON.")

    from langgraph.types import Command

    meta = _SESSIONS.get(session, {"session": session, "autonomy": "L2", "source": "?", "runs": None})
    return StreamingResponse(
        _stream_events(Command(resume=parsed), config, session, meta),
        media_type="application/x-ndjson",
    )
