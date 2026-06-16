"""
Starter unit tests for the deterministic core (spec §4 — Unit layer).

These run with zero external deps beyond pytest. They demonstrate the pattern Claude Code
should follow for every node: hand-construct inputs, assert exact deterministic outputs.

Run:  pytest -q
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.state import TestResult, AutonomyLevel, initial_state  # noqa: E402
from test_data_mining.nodes.flaky_detect import flaky_detect, score_test     # noqa: E402


def _run(test_id: str, outcome: str, run_id: str) -> TestResult:
    return TestResult(
        test_id=test_id, suite="s", outcome=outcome, duration_sec=0.1,
        run_id=run_id, commit_sha="abc", timestamp=f"2026-01-0{run_id}T00:00:00Z",
    )


def test_score_pure_pass_is_not_flaky():
    runs = [_run("t", "passed", str(i)) for i in range(1, 6)]
    score, p, f = score_test(runs)
    assert score == 0.0 and p == 5 and f == 0


def test_score_50_50_is_max_flaky():
    runs = [_run("t", "passed", str(i)) for i in range(1, 4)] + \
           [_run("t", "failed", str(i)) for i in range(4, 7)]
    score, p, f = score_test(runs)
    assert score == 1.0 and p == 3 and f == 3


def test_flaky_detect_labels_correctly():
    # 6 runs: 4 pass / 2 fail -> flaky; >= min_runs(5); score = 1 - 2/6 = 0.667 >= cutoff
    flaky_runs = [_run("flaky.test", "passed", str(i)) for i in range(1, 5)] + \
                 [_run("flaky.test", "failed", str(i)) for i in range(5, 7)]
    # 6 runs all fail -> stable (real regression, NOT flaky)
    fail_runs = [_run("broken.test", "failed", str(i)) for i in range(1, 7)]
    # 2 runs -> insufficient history
    new_runs = [_run("new.test", "passed", "1"), _run("new.test", "passed", "2")]

    state = initial_state("unused", autonomy_level=AutonomyLevel.L1_ASSISTIVE)
    state["raw_results"] = flaky_runs + fail_runs + new_runs
    out = flaky_detect(state)

    verdicts = {f.test_id: f.verdict for f in out["flaky_findings"]}
    assert verdicts["flaky.test"] == "flaky"
    assert verdicts["broken.test"] == "stable"        # all-fail must not be flaky
    assert verdicts["new.test"] == "insufficient_history"
