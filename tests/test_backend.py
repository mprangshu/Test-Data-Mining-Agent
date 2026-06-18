"""
Tests for the v2 FastAPI backend (/mine streams to the review gate, /resume completes).
Run: pytest -q tests/test_backend.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))

from fastapi.testclient import TestClient   # noqa: E402

from backend.app import app                 # noqa: E402

client = TestClient(app)

_TEST_CASES_CSV = (
    "order_id,email,currency,scenario_tag,data_category\n"
    "ORD-1,a@b.com,USD,typical,valid\n"
    "ORD-2,,USD,missing_email,negative\n"
)

_JUNIT = (
    '<testsuite name="order_flow">'
    '  <testcase classname="order_flow" name="typical">'
    '    <properties>'
    '      <property name="scenario_type" value="valid"/>'
    '      <property name="email" value="a@b.com"/>'
    '      <property name="currency" value="USD"/>'
    '    </properties>'
    '  </testcase>'
    '</testsuite>'
)


def _events(resp):
    return [json.loads(line) for line in resp.text.strip().splitlines() if line.strip()]


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_mine_streams_to_review_then_resume_completes():
    resp = client.post(
        "/mine",
        files=[
            ("test_cases", ("order_flow_tests.csv", _TEST_CASES_CSV.encode(), "text/csv")),
            ("results", ("junit.xml", _JUNIT.encode(), "application/xml")),
        ],
    )
    assert resp.status_code == 200, resp.text
    ev = _events(resp)
    nodes = {e["node"] for e in ev if e["type"] == "node"}
    assert {"parse", "load_results", "mongo_lookup", "vector_search", "coverage_gap", "generate"} <= nodes

    interrupts = [e for e in ev if e["type"] == "interrupt"]
    assert len(interrupts) == 1
    assert not any(e["type"] == "result" for e in ev)        # paused at the gate
    payload = interrupts[0]["payload"]
    session = interrupts[0]["session"]
    fields = {f["field_name"] for f in payload["fields"]}
    assert {"order_id", "email", "currency"} <= fields
    assert all(f["sets"] for f in payload["fields"])         # every field offers >= 1 set

    # Resume: choose gen_A for every field.
    selections = [{"field_name": f["field_name"], "include": True, "chosen_set_id": "gen_A"}
                  for f in payload["fields"]]
    r2 = client.post("/resume", data={"session": session, "review_selections": json.dumps(selections)})
    assert r2.status_code == 200, r2.text
    ev2 = _events(r2)
    nodes2 = {e["node"] for e in ev2 if e["type"] == "node"}
    assert {"synthesise", "persist"} <= nodes2
    results = [e for e in ev2 if e["type"] == "result"]
    assert len(results) == 1
    res = results[0]
    assert res["report"]["row_count"] >= 1
    assert res["final_dataset"]                              # rows produced
    assert "email" in res["final_dataset"][0]


def test_mine_requires_test_cases():
    resp = client.post("/mine", files=[("results", ("j.xml", _JUNIT.encode(), "application/xml"))])
    assert resp.status_code == 422


def test_mine_rejects_bad_test_case_ext():
    resp = client.post("/mine", files=[("test_cases", ("notes.pdf", b"x", "application/pdf"))])
    assert resp.status_code == 422


def test_resume_unknown_session_404():
    assert client.post("/resume", data={"session": "nope", "review_selections": "[]"}).status_code == 404


def _mine_and_resume():
    resp = client.post("/mine", files=[
        ("test_cases", ("order_flow_tests.csv", _TEST_CASES_CSV.encode(), "text/csv")),
        ("results", ("junit.xml", _JUNIT.encode(), "application/xml")),
    ])
    intr = [e for e in _events(resp) if e["type"] == "interrupt"][0]
    sels = [{"field_name": f["field_name"], "include": True, "chosen_set_id": "gen_A"}
            for f in intr["payload"]["fields"]]
    client.post("/resume", data={"session": intr["session"], "review_selections": json.dumps(sels)})
    return intr["session"]


def test_persist_saves_dataset(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "mongo"))
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    session = _mine_and_resume()
    r = client.post("/persist", data={"session": session, "save": "true",
                                      "label": "order_flow_v2", "tags": "order,generated"})
    body = r.json()
    assert body["saved"] is True
    assert body["receipt"]["label"] == "order_flow_v2"
    assert (tmp_path / "mongo" / "order_flow_v2.json").exists()


def test_persist_skip_does_not_save(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "mongo"))
    session = _mine_and_resume()
    body = client.post("/persist", data={"session": session, "save": "false"}).json()
    assert body == {"saved": False}
