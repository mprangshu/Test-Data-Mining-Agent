"""
Integration tests — full v2 graph state flow (pivot §13 demo story).

Drives the compiled graph end-to-end: parse → gather → coverage_gap → generate → review
(interrupt) → resume → synthesise → persist, then verifies the save→reuse loop. Stores are
redirected to tmp so the repo seeds are untouched.

Run: pytest -q tests/test_integration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from test_data_mining.graph import build_graph                  # noqa: E402
from test_data_mining.nodes.review import auto_selections       # noqa: E402
from test_data_mining.nodes.mongo_lookup import mongo_lookup    # noqa: E402
from test_data_mining.state import ParsedField, initial_state   # noqa: E402

_TC_CSV = (
    "order_id,email,currency,scenario_tag,data_category\n"
    "ORD-1,a@b.com,USD,typical,valid\n"
    "ORD-2,,USD,missing_email,negative\n"
)
_JUNIT = (
    '<testsuite name="of"><testcase classname="of" name="typical"><properties>'
    '<property name="scenario_type" value="valid"/>'
    '<property name="email" value="a@b.com"/>'
    '<property name="currency" value="USD"/>'
    '</properties></testcase></testsuite>'
)


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "mongo"))
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))


def _inputs(tmp_path) -> str:
    (tmp_path / "test_cases").mkdir(parents=True, exist_ok=True)
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "test_cases" / "order_flow_tests.csv").write_text(_TC_CSV, encoding="utf-8")
    (tmp_path / "results" / "junit.xml").write_text(_JUNIT, encoding="utf-8")
    return str(tmp_path)


def test_full_pipeline_interrupt_resume(tmp_path):
    from langgraph.types import Command

    g = build_graph()
    cfg = {"configurable": {"thread_id": "it-full"}}
    g.invoke(initial_state(_inputs(tmp_path / "in")), config=cfg)
    assert g.get_state(cfg).next == ("review",)               # paused at the gate

    cands = g.get_state(cfg).values["candidate_sets"]
    g.invoke(Command(resume={"review_selections": auto_selections(cands)}), config=cfg)

    final = g.get_state(cfg).values
    assert g.get_state(cfg).next == ()                        # completed
    assert final["final_dataset"]                             # rows produced
    assert final["report"]["row_count"] >= 1
    assert "email" in final["final_dataset"][0]


def test_save_back_then_reuse(tmp_path, monkeypatch):
    from test_data_mining.nodes.persist import write_dataset

    rows = [{"email": "x@y.com", "currency": "USD", "scenario_tag": "t", "data_category": "generated"}]
    write_dataset(rows, "order_flow_v9", ["order"])           # save under the tmp store

    st = initial_state("x")
    st["parsed_fields"] = [ParsedField("email", "Identity", ["required"], [], ["valid"])]
    assert "order_flow_v9" in {e.label for e in mongo_lookup(st)["existing_data"]}


def test_unseeded_when_no_results(tmp_path):
    """No result files → load_results notes it (unseeded), pipeline still pauses at review."""
    from langgraph.types import Command

    base = tmp_path / "noresults"
    (base / "test_cases").mkdir(parents=True)
    (base / "test_cases" / "tc.csv").write_text(_TC_CSV, encoding="utf-8")

    g = build_graph()
    cfg = {"configurable": {"thread_id": "it-noresults"}}
    g.invoke(initial_state(str(base)), config=cfg)
    state = g.get_state(cfg).values
    assert g.get_state(cfg).next == ("review",)
    assert state["seed_values"] == []
    assert any("unseeded" in gap for gap in state["gaps"])
