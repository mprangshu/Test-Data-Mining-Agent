"""
Integration tests — full graph state flow (spec §4, Integration layer).

Exercises the compiled LangGraph end-to-end per autonomy level, the HITL interrupt/resume
path, and graceful degradation on missing input — the real graph, not mocked nodes.

Run:  pytest -q tests/test_integration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from test_data_mining.graph import build_graph                       # noqa: E402
from test_data_mining.state import AutonomyLevel, initial_state      # noqa: E402
import test_data_mining.nodes.persist as persist_mod                 # noqa: E402

_OUTCOMES = ["passed", "passed", "passed", "passed", "failed", "failed"]


def _junit(cases: list[tuple[str, str]]) -> str:
    parts = ['<testsuite name="s">']
    for tid, outcome in cases:
        cn, _, nm = tid.partition("#")
        if outcome == "passed":
            parts.append(f'<testcase classname="{cn}" name="{nm}" time="0.1"/>')
        else:
            parts.append(f'<testcase classname="{cn}" name="{nm}" time="0.1">'
                         f'<failure message="boom">trace</failure></testcase>')
    parts.append("</testsuite>")
    return "\n".join(parts)


def _build_runs(root: Path, n: int = 6) -> str:
    for i in range(n):
        d = root / f"run_{i:02d}"
        d.mkdir(parents=True)
        (d / "results.xml").write_text(_junit([
            ("flaky.T#a", _OUTCOMES[i]),
            ("stable.T#s", "passed"),
            ("broken.T#b", "failed"),   # always-fail regression — must NOT be flaky
        ]), encoding="utf-8")
    return str(root)


@pytest.fixture(autouse=True)
def _reports_to_tmp(monkeypatch, tmp_path):
    # Keep persisted report files out of the repo's data/reports during tests.
    monkeypatch.setattr(persist_mod, "_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("MONGODB_URI", raising=False)


def test_full_graph_l1(tmp_path):
    g = build_graph()
    path = _build_runs(tmp_path / "in")
    out = g.invoke(initial_state(path, AutonomyLevel.L1_ASSISTIVE),
                   config={"configurable": {"thread_id": "it-l1"}})
    assert out["validation_ok"] is True
    assert "flaky.T#a" in out["report"]["flaky"]
    assert "broken.T#b" not in out["report"]["flaky"]      # regression not mislabelled
    assert out["report"]["persisted_to"].endswith(".json")
    assert out["report"]["recommendations"]


def test_full_graph_l3_runs_without_pause(tmp_path):
    g = build_graph()
    path = _build_runs(tmp_path / "in")
    cfg = {"configurable": {"thread_id": "it-l3"}}
    out = g.invoke(initial_state(path, AutonomyLevel.L3_GOAL_DRIVEN), config=cfg)
    assert g.get_state(cfg).next == ()                     # completed, no pending review
    assert out["report"]["persisted_to"]


def test_l2_interrupts_then_resumes_with_dismissal(tmp_path):
    from langgraph.types import Command

    g = build_graph()
    path = _build_runs(tmp_path / "in")
    cfg = {"configurable": {"thread_id": "it-l2"}}

    g.invoke(initial_state(path, AutonomyLevel.L2_SUPERVISED), config=cfg)
    assert g.get_state(cfg).next == ("review",)            # paused at the gate

    g.invoke(Command(resume={"dismissed_flaky": ["flaky.T#a"]}), config=cfg)
    final = g.get_state(cfg).values
    assert final["report"]["persisted_to"]
    assert "flaky.T#a" not in final["report"]["flaky"]     # dismissal honoured downstream


def test_missing_input_degrades_gracefully(tmp_path):
    g = build_graph()
    out = g.invoke(initial_state(str(tmp_path / "does_not_exist"), AutonomyLevel.L1_ASSISTIVE),
                   config={"configurable": {"thread_id": "it-missing"}})
    assert out["validation_ok"] is False                   # no crash
    assert out["report"]["flaky"] == []
    assert any("not found" in g_ for g_ in out["gaps"])
