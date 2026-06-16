"""
Unit tests for failure_clustering (G3, spec §2.6) — signature normalisation, vector
clustering, and grounded labelling.

Run:  pytest -q tests/test_failure_clustering.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.state import TestResult, initial_state                       # noqa: E402
from test_data_mining.nodes.failure_clustering import (                            # noqa: E402
    deterministic_label, failure_clustering, normalise_signature, _grounded,
)


def _fail(test_id: str, message: str, run_id: str, stack: str = "trace") -> TestResult:
    return TestResult(
        test_id=test_id, suite="s", outcome="failed", duration_sec=0.1,
        run_id=run_id, commit_sha="c", timestamp="2026-01-01T00:00:00Z",
        message=message, stack_trace=stack,
    )


def test_normalise_collapses_numbers_and_addresses():
    a = normalise_signature("expected status 200 but got 500")
    b = normalise_signature("expected status 201 but got 503")
    assert a == b                       # status codes normalised away
    assert "#" in a
    c = normalise_signature("timeout after 5000ms at 0xAF12")
    assert "0x#" in c and "#ms" not in c   # ms stripped with the number


def test_clusters_group_by_root_cause_not_exact_text():
    # 3 timeouts (different ms), 2 HTTP-500ish (different codes), 1 unique -> 3 clusters.
    results = [
        _fail("t.a", "TimeoutError: waiting for selector exceeded 5000ms", "0"),
        _fail("t.b", "TimeoutError: waiting for selector exceeded 8000ms", "1"),
        _fail("t.c", "TimeoutError: waiting for selector exceeded 3000ms", "2"),
        _fail("t.d", "AssertionError: expected status 200 but got 500", "0"),
        _fail("t.e", "AssertionError: expected status 200 but got 503", "1"),
        _fail("t.f", "ConnectionResetError: connection reset by peer", "0"),
    ]
    state = initial_state("x")
    state["raw_results"] = results
    clusters = failure_clustering(state)["failure_clusters"]

    counts = sorted(c.count for c in clusters)
    assert counts == [1, 2, 3]
    assert sum(c.count for c in clusters) == 6
    assert all(c.label for c in clusters)            # every cluster is labelled
    assert all(c.cluster_id for c in clusters)


def test_no_failures_yields_no_clusters():
    state = initial_state("x")
    state["raw_results"] = [
        TestResult(test_id="ok", suite="s", outcome="passed", duration_sec=0.1,
                   run_id="0", commit_sha="c", timestamp="t"),
    ]
    assert failure_clustering(state)["failure_clusters"] == []


def test_deterministic_label_uses_error_type():
    label = deterministic_label("TimeoutError: waiting for selector exceeded #ms")
    assert label.startswith("TimeoutError")


def test_grounded_rejects_hallucinated_label():
    msgs = ["TimeoutError: waiting for selector exceeded 5000ms"]
    assert _grounded("Timeout waiting selector", msgs) is True
    assert _grounded("database deadlock contention", msgs) is False
