"""
flaky_detect.py — Deterministic flaky-test detection (G1).

Type: deterministic, fully reproducible. This is a WORKING reference implementation.

Definition we use
-----------------
A test is flaky if, *at the same commit_sha*, it both passed and failed across runs.
A test that fails in every run is NOT flaky — it's a real regression (kept separate so
it is not mislabelled). The flakiness score is the normalised "flip" rate:

    flakiness_score = 1 - |pass_count - fail_count| / runs_observed       # if both seen
                    = 0                                                    # if only one outcome

This peaks at 1.0 for a perfect 50/50 split and falls toward 0 as the test leans to one
side. A test is reported "flaky" when it has BOTH outcomes AND score >= flaky_score_cutoff,
provided it has >= min_runs_for_flaky observations; otherwise "insufficient_history".

NOTE: this is intentionally simple and explainable. More advanced detectors (e.g. weighting
recent runs, ignoring skips, per-commit grouping across multiple commits) are a good
follow-up — see ROADMAP.md. Keep it deterministic; never ask an LLM for the score.
"""
from __future__ import annotations

from collections import defaultdict

from ..state import AgentState, FlakyFinding, TestResult


def _group_by_test(results: list[TestResult]) -> dict[str, list[TestResult]]:
    grouped: dict[str, list[TestResult]] = defaultdict(list)
    for r in results:
        # Only same-commit runs count toward flaky detection (spec §1.4).
        grouped[r.test_id].append(r)
    return grouped


def score_test(runs: list[TestResult]) -> tuple[float, int, int]:
    """Return (flakiness_score, pass_count, fail_count) for one test's runs."""
    passes = sum(1 for r in runs if r.outcome == "passed")
    fails = sum(1 for r in runs if r.outcome in ("failed", "error"))
    observed = passes + fails
    if observed == 0 or passes == 0 or fails == 0:
        return 0.0, passes, fails
    score = 1.0 - abs(passes - fails) / observed
    return round(score, 4), passes, fails


def flaky_detect(state: AgentState) -> dict:
    """LangGraph node: compute a FlakyFinding per test."""
    results = state.get("raw_results", [])
    min_runs = state.get("min_runs_for_flaky", 5)
    cutoff = state.get("flaky_score_cutoff", 0.2)
    min_minority = state.get("min_minority_fails", 2)

    findings: list[FlakyFinding] = []
    for test_id, runs in _group_by_test(results).items():
        score, passes, fails = score_test(runs)
        observed = passes + fails
        minority = min(passes, fails)
        last_failure = max(
            (r.timestamp for r in runs if r.outcome in ("failed", "error")),
            default=None,
        )

        if observed < min_runs:
            verdict = "insufficient_history"
        elif passes > 0 and fails > 0 and minority >= min_minority and score >= cutoff:
            # Both outcomes seen, minority appears enough times to rule out a one-off,
            # and the flip rate clears the cutoff.
            verdict = "flaky"
        else:
            verdict = "stable"

        findings.append(FlakyFinding(
            test_id=test_id,
            flakiness_score=score,
            runs_observed=observed,
            pass_count=passes,
            fail_count=fails,
            last_failure_ts=last_failure,
            verdict=verdict,                          # type: ignore[arg-type]
        ))

    findings.sort(key=lambda f: f.flakiness_score, reverse=True)
    n_flaky = sum(1 for f in findings if f.verdict == "flaky")
    print(f"NODE_EXIT flaky_detect: {n_flaky} flaky of {len(findings)} tests")
    return {"flaky_findings": findings}
