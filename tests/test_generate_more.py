"""
Phase 4 acceptance — the iterative loop (CONTEXT-v3 §1, Q2 = replace).

mine → resume → pick rows → POST /generate-more → a fresh grounded round seeded by the selection.
Asserts: round_index increments; the picked rows carry over as the new base (source=input); the
working set is replaced (seeded by the selection); provenance + clean rows still hold.

Run: pytest -q tests/test_generate_more.py
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
    "ORD-2,c@d.com,GBP,typical2,valid\n"
)


def _events(resp):
    return [json.loads(line) for line in resp.text.strip().splitlines() if line.strip()]


def _mine_and_resume():
    resp = client.post("/mine", files=[("test_cases", ("tc.csv", _TEST_CASES_CSV.encode(), "text/csv"))])
    assert resp.status_code == 200, resp.text
    intr = next(e for e in _events(resp) if e["type"] == "interrupt")
    session, payload = intr["session"], intr["payload"]
    selections = [{"field_name": f["field_name"], "include": True, "chosen_set_id": "gen_A"}
                  for f in payload["fields"]]
    r2 = client.post("/resume", data={"session": session, "review_selections": json.dumps(selections)})
    assert r2.status_code == 200, r2.text
    result = next(e for e in _events(r2) if e["type"] == "result")
    return session, result


def test_generate_more_replaces_round_seeded_by_selection():
    session, result = _mine_and_resume()
    assert result["output_rows"]
    # pick two rows the analyst "likes" (their clean fields)
    picked = [r["fields"] for r in result["output_rows"][:2]]

    r3 = client.post("/generate-more",
                     data={"session": session, "seed_selection": json.dumps(picked)})
    assert r3.status_code == 200, r3.text
    out = r3.json()
    assert out["round_index"] == 1                       # incremented from round 0
    assert out["output_rows"]
    assert out["final_dataset"]
    # the picked rows carry over as the new base, tagged input (REPLACE: seeded by selection)
    inputs = [r for r in out["output_rows"] if r["source"] == "input"]
    assert len(inputs) == len(picked)
    assert [r["fields"] for r in inputs] == picked
    # clean CSV rows still carry no provenance keys
    for row in out["final_dataset"]:
        assert "source" not in row and "row_uid" not in row
    # a second round increments again and re-seeds from the new selection
    picked2 = [r["fields"] for r in out["output_rows"] if r["source"] == "generated"][:1]
    r4 = client.post("/generate-more",
                     data={"session": session, "seed_selection": json.dumps(picked2)})
    assert r4.status_code == 200, r4.text
    assert r4.json()["round_index"] == 2


def test_generate_more_requires_selection():
    session, _ = _mine_and_resume()
    r = client.post("/generate-more", data={"session": session, "seed_selection": "[]"})
    assert r.status_code == 422


def test_generate_more_unknown_session_404():
    r = client.post("/generate-more",
                    data={"session": "nope", "seed_selection": json.dumps([{"x": 1}])})
    assert r.status_code == 404
