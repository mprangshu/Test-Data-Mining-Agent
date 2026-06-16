"""
Unit tests for synthesis (G5 ranking + grounded recommendations) and persist (run store).

Run:  pytest -q tests/test_synthesis_persist.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.state import (                                  # noqa: E402
    FailureCluster, FlakyFinding, SuiteHealth, initial_state,
)
from test_data_mining.nodes.synthesis import synthesis               # noqa: E402
from test_data_mining.nodes.persist import persist                   # noqa: E402


def _flaky(test_id, score, p, f):
    return FlakyFinding(test_id=test_id, flakiness_score=score, runs_observed=p + f,
                        pass_count=p, fail_count=f, last_failure_ts=None, verdict="flaky")


def _state_with_findings():
    state = initial_state("x")
    state["flaky_findings"] = [
        _flaky("pkg.A#hi", 0.67, 4, 2),
        _flaky("pkg.B#lo", 0.30, 7, 3),
        FlakyFinding("pkg.C#stable", 0.0, 6, 6, 0, None, "stable"),
    ]
    state["failure_clusters"] = [
        FailureCluster("c000", "AssertionError: expected status # but got #", 6, "trace", label="API 500s"),
        FailureCluster("c001", "TimeoutError: waiting for selector exceeded #", 2, "trace", label="Timeouts"),
    ]
    state["suite_health"] = SuiteHealth(pass_rate=0.88, mean_duration_sec=1.1, flake_rate=0.17, window_runs=10)
    return state


def test_synthesis_ranks_and_grounds():
    report = synthesis(_state_with_findings())["report"]
    assert report["generated_by"] == "deterministic"
    assert report["summary"].startswith("2 flaky test(s), 2 recurring")

    # Highest severity first: the count-6 cluster and the 0.67 flaky are "high".
    sev = [p["severity"] for p in report["priorities"]]
    assert sev == sorted(sev, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])
    assert report["priorities"][0]["severity"] == "high"

    # Recommendations are grounded — they name real findings, not placeholders.
    joined = " ".join(report["recommendations"])
    assert "pkg.A#hi" in joined
    assert "TODO" not in joined
    assert report["flaky"] == ["pkg.A#hi", "pkg.B#lo"]   # stable excluded, sorted by score


def test_synthesis_respects_review_dismissals():
    state = _state_with_findings()
    state["review_decisions"] = {"dismissed_flaky": ["pkg.A#hi"], "dismissed_clusters": ["c000"]}
    report = synthesis(state)["report"]
    assert "pkg.A#hi" not in report["flaky"]
    assert all(c["count"] != 6 for c in report["clusters"])


def test_synthesis_healthy_suite_has_positive_note():
    state = initial_state("x")
    state["flaky_findings"] = []
    state["failure_clusters"] = []
    state["suite_health"] = SuiteHealth(pass_rate=1.0, mean_duration_sec=0.5, flake_rate=0.0, window_runs=10)
    report = synthesis(state)["report"]
    assert any("healthy" in r.lower() for r in report["recommendations"])


def test_persist_writes_local_file(monkeypatch, tmp_path):
    # Ensure no Mongo path and redirect the reports dir to a temp location.
    monkeypatch.delenv("MONGODB_URI", raising=False)
    import test_data_mining.nodes.persist as persist_mod
    monkeypatch.setattr(persist_mod, "_REPORTS_DIR", str(tmp_path))

    state = initial_state("x")
    state["report"] = synthesis(_state_with_findings())["report"]
    out = persist(state)

    location = out["report"]["persisted_to"]
    assert location.endswith(".json")
    assert os.path.exists(location)
    with open(location, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["suite_health"]["pass_rate"] == 0.88     # dataclass encoded
    assert "recommendations" in doc and doc["priorities"]
