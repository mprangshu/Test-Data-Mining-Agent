"""
Tests for the demo FastAPI backend (BUILD-PLAN Phase 2).

Drives the app in-process with FastAPI's TestClient — no running server needed. Covers both
input modes (upload files / paste text), the insufficient-history honesty path, and the
input-guard error cases.

Run:  pytest -q tests/test_backend.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))           # so `import backend.app` resolves
sys.path.insert(0, str(_REPO / "src"))   # so the agent package resolves

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402

client = TestClient(app)


def _junit(cases: list[tuple[str, str]]) -> str:
    """Build a tiny JUnit XML from (test_id, outcome) pairs."""
    parts = ['<testsuite name="s">']
    for tid, outcome in cases:
        classname, _, name = tid.partition("#")
        if outcome == "passed":
            parts.append(f'<testcase classname="{classname}" name="{name}" time="0.1"/>')
        else:
            parts.append(
                f'<testcase classname="{classname}" name="{name}" time="0.1">'
                f'<failure message="boom">trace line</failure></testcase>'
            )
    parts.append("</testsuite>")
    return "\n".join(parts)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_analyse_text_single_run_is_insufficient_history():
    xml = _junit([("pkg.T#a", "passed"), ("pkg.T#b", "failed")])
    resp = client.post("/analyse", data={"autonomy": "L1", "format": "junit", "text": xml})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["validation_ok"] is True
    assert body["meta"]["runs"] == 1
    # One run -> flaky detection cannot conclude; validate flags it honestly.
    assert any("insufficient_history" in g for g in body["gaps"])
    verdicts = {f["test_id"]: f["verdict"] for f in body["flaky_findings"]}
    assert verdicts["pkg.T#a"] == "insufficient_history"


def test_analyse_files_multi_run_detects_flaky():
    # 6 runs (one file each): flaky.T#a passes 4x / fails 2x -> flaky; stable.T#s always passes.
    outcomes = ["passed", "passed", "passed", "passed", "failed", "failed"]
    files = []
    for i, out in enumerate(outcomes):
        xml = _junit([("flaky.T#a", out), ("stable.T#s", "passed")])
        files.append(("files", (f"run_{i}.xml", xml.encode(), "application/xml")))
    resp = client.post("/analyse", data={"autonomy": "L1"}, files=files)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["runs"] == 6
    verdicts = {f["test_id"]: f["verdict"] for f in body["flaky_findings"]}
    assert verdicts["flaky.T#a"] == "flaky"
    assert verdicts["stable.T#s"] == "stable"
    assert "flaky.T#a" in body["report"]["flaky"]


def test_analyse_rejects_both_inputs():
    xml = _junit([("pkg.T#a", "passed")])
    resp = client.post(
        "/analyse",
        data={"autonomy": "L1", "text": xml},
        files=[("files", ("r.xml", xml.encode(), "application/xml"))],
    )
    assert resp.status_code == 422


def test_analyse_rejects_no_input():
    assert client.post("/analyse", data={"autonomy": "L1"}).status_code == 422


def test_analyse_rejects_bad_extension():
    resp = client.post(
        "/analyse",
        data={"autonomy": "L1"},
        files=[("files", ("r.txt", b"nope", "text/plain"))],
    )
    assert resp.status_code == 422


def test_analyse_rejects_bad_autonomy():
    xml = _junit([("pkg.T#a", "passed")])
    resp = client.post("/analyse", data={"autonomy": "L9", "format": "junit", "text": xml})
    assert resp.status_code == 422


def test_analyse_stream_emits_node_events_then_result():
    outcomes = ["passed", "passed", "passed", "passed", "failed", "failed"]
    files = [
        ("files", (f"run_{i}.xml",
                   _junit([("flaky.T#a", o), ("stable.T#s", "passed")]).encode(),
                   "application/xml"))
        for i, o in enumerate(outcomes)
    ]
    resp = client.post("/analyse/stream", data={"autonomy": "L1"}, files=files)
    assert resp.status_code == 200, resp.text

    events = [json.loads(line) for line in resp.text.strip().splitlines() if line.strip()]
    node_events = [e for e in events if e["type"] == "node"]
    # Every node carries a summary + a numeric elapsed time.
    assert all("summary" in e and isinstance(e["elapsed_ms"], int) for e in node_events)
    nodes = {e["node"] for e in node_events}
    assert {"ingest", "validate", "flaky_detect", "suite_health", "synthesis", "persist"} <= nodes

    results = [e for e in events if e["type"] == "result"]
    assert len(results) == 1
    r = results[0]
    verdicts = {f["test_id"]: f["verdict"] for f in r["flaky_findings"]}
    assert verdicts["flaky.T#a"] == "flaky"
    assert "flaky.T#a" in r["report"]["flaky"]


def test_analyse_stream_rejects_no_input():
    assert client.post("/analyse/stream", data={"autonomy": "L1"}).status_code == 422


def _six_run_flaky_files():
    outcomes = ["passed", "passed", "passed", "passed", "failed", "failed"]
    return [
        ("files", (f"run_{i}.xml",
                   _junit([("flaky.T#a", o), ("stable.T#s", "passed")]).encode(),
                   "application/xml"))
        for i, o in enumerate(outcomes)
    ]


def test_l2_pauses_at_review_then_resumes_with_dismissal():
    # L2 run streams up to the review gate and PAUSES (no result yet).
    r1 = client.post("/analyse/stream", data={"autonomy": "L2"}, files=_six_run_flaky_files())
    assert r1.status_code == 200, r1.text
    ev1 = [json.loads(line) for line in r1.text.strip().splitlines() if line.strip()]
    interrupts = [e for e in ev1 if e["type"] == "interrupt"]
    assert len(interrupts) == 1
    assert not any(e["type"] == "result" for e in ev1)          # paused — nothing persisted yet
    session = interrupts[0]["session"]
    findings = interrupts[0]["findings"]
    assert any(f["test_id"] == "flaky.T#a" for f in findings["flaky"])

    # Resume, dismissing the flaky finding → it must be excluded from the final report.
    r2 = client.post("/resume", data={"session": session,
                                      "decisions": json.dumps({"dismissed_flaky": ["flaky.T#a"]})})
    assert r2.status_code == 200, r2.text
    ev2 = [json.loads(line) for line in r2.text.strip().splitlines() if line.strip()]
    nodes = {e["node"] for e in ev2 if e["type"] == "node"}
    assert {"synthesis", "persist"} <= nodes                    # continued past the gate
    results = [e for e in ev2 if e["type"] == "result"]
    assert len(results) == 1
    assert "flaky.T#a" not in results[0]["report"]["flaky"]     # dismissal honoured


def test_l1_does_not_pause():
    r = client.post("/analyse/stream", data={"autonomy": "L1"}, files=_six_run_flaky_files())
    ev = [json.loads(line) for line in r.text.strip().splitlines() if line.strip()]
    assert not any(e["type"] == "interrupt" for e in ev)        # L1 skips the review gate
    assert any(e["type"] == "result" for e in ev)


def test_resume_unknown_session_404():
    assert client.post("/resume", data={"session": "nope", "decisions": "{}"}).status_code == 404
