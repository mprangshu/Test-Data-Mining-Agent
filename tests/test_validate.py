"""
Unit tests for the deterministic `validate` and `suite_health` nodes (spec §2.3, §4).

Mirrors the pattern in test_flaky_detect.py: hand-construct inputs, assert exact outputs.
Run:  pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.state import TestResult, initial_state          # noqa: E402
from test_data_mining.nodes.stubs import validate, suite_health        # noqa: E402


def _run(test_id: str, outcome: str, run_id: str, dur: float = 0.1) -> TestResult:
    return TestResult(
        test_id=test_id, suite="s", outcome=outcome, duration_sec=dur,
        run_id=run_id, commit_sha="abc", timestamp="2026-01-01T00:00:00Z",
    )


def test_validate_empty_is_not_ok():
    state = initial_state("unused")
    state["raw_results"] = []
    out = validate(state)
    assert out["validation_ok"] is False
    assert any("no parseable results" in g for g in out["gaps"])


def test_validate_sufficient_history_ok_no_gap():
    # 5 distinct runs == default min_runs_for_flaky -> no insufficient-history gap.
    state = initial_state("unused", min_runs_for_flaky=5)
    state["raw_results"] = [_run("t", "passed", str(i)) for i in range(5)]
    out = validate(state)
    assert out["validation_ok"] is True
    assert out["gaps"] == []


def test_validate_thin_history_flags_gap_but_stays_ok():
    # Only 2 runs but min is 5 -> still ok (valid answer), with an insufficient-history gap.
    state = initial_state("unused", min_runs_for_flaky=5)
    state["raw_results"] = [_run("t", "passed", "0"), _run("t", "failed", "1")]
    out = validate(state)
    assert out["validation_ok"] is True
    assert any("insufficient_history" in g for g in out["gaps"])


def test_suite_health_basic_metrics():
    # 3 passed / 1 failed across 2 runs -> pass_rate 0.75, window_runs 2.
    state = initial_state("unused")
    state["raw_results"] = [
        _run("a", "passed", "0", dur=1.0), _run("b", "passed", "0", dur=1.0),
        _run("a", "passed", "1", dur=2.0), _run("b", "failed", "1", dur=0.0),
    ]
    out = suite_health(state)
    h = out["suite_health"]
    assert h.pass_rate == 0.75
    assert h.window_runs == 2
    assert h.mean_duration_sec == 1.0


def test_suite_health_empty_is_none():
    state = initial_state("unused")
    state["raw_results"] = []
    assert suite_health(state)["suite_health"] is None
