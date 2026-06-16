"""
Stub nodes for the Test Data Mining Agent.

These are deliberately minimal so Claude Code has clear rails to fill in. Each function
already has the right signature and returns the right state keys — implement the body per
the referenced spec section. The deterministic core (ingest, flaky_detect) is already real;
build these in ROADMAP order.

KEEP THE INVARIANTS (see CLAUDE.md): read-only, no Neo4j, deterministic detectors before LLM.
"""
from __future__ import annotations

from ..state import AgentState, SuiteHealth


# --------------------------------------------------------------------------- #
# validate — deterministic (spec §2.3)
# --------------------------------------------------------------------------- #
def validate(state: AgentState) -> dict:
    """Quality gates: flag corrupt/insufficient data; set validation_ok.

    Rules (spec §1.4):
      * Empty input -> validation_ok=False + a gap note. The downstream detectors still
        run and degrade gracefully (they handle empty raw_results).
      * Too little history is NOT a failure — it's a valid answer. We keep validation_ok=True
        and flag a gap so the reader knows flaky verdicts will be "insufficient_history".
      * Never raise — partial data flows through.
    """
    results = state.get("raw_results", [])
    min_runs = state.get("min_runs_for_flaky", 5)

    if not results:
        print("NODE_EXIT validate: validation_ok=False (no parseable results)")
        return {"validation_ok": False, "gaps": ["validate: no parseable results found"]}

    n_runs = len({r.run_id for r in results})
    gaps: list[str] = []
    if n_runs < min_runs:
        gaps.append(
            f"validate: only {n_runs} run(s) present; flaky detection needs >= {min_runs} "
            f"runs at the same version — affected tests will report 'insufficient_history'"
        )

    print(f"NODE_EXIT validate: validation_ok=True, {len(results)} results across {n_runs} runs")
    return {"validation_ok": True, "gaps": gaps}


# --------------------------------------------------------------------------- #
# coverage_gap — deterministic (spec §2.3, G2). MVP: module/file level only.
# --------------------------------------------------------------------------- #
def coverage_gap(state: AgentState) -> dict:
    """Surface modules with low/missing/declining coverage.

    MVP TODO:
      * parse JaCoCo XML / lcov reports straight from the run (Phase 2 input — may be absent
        in current fixtures, so return [] + a gap note if no coverage data is present).
    Phase 2: requirement-level gaps via MongoDB requirement_id refs (shallow join, NO graph DB).
    """
    # No coverage reports in the MVP fixtures yet — declare the gap honestly.
    return {"coverage_findings": [], "gaps": ["coverage_gap: no coverage reports in input (Phase 2)"]}


# --------------------------------------------------------------------------- #
# failure_clustering now lives in nodes/failure_clustering.py (ChromaDB vector clustering).
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# suite_health — deterministic (G4). Often folded into flaky/coverage pass.
# --------------------------------------------------------------------------- #
def suite_health(state: AgentState) -> dict:
    """Compute pass rate / mean duration / flake rate over the window."""
    results = state.get("raw_results", [])
    if not results:
        return {"suite_health": None}
    passed = sum(1 for r in results if r.outcome == "passed")
    mean_dur = sum(r.duration_sec for r in results) / len(results)
    flaky = sum(1 for f in state.get("flaky_findings", []) if f.verdict == "flaky")
    n_tests = len({r.test_id for r in results})
    health = SuiteHealth(
        pass_rate=round(passed / len(results), 4),
        mean_duration_sec=round(mean_dur, 4),
        flake_rate=round(flaky / n_tests, 4) if n_tests else 0.0,
        window_runs=len({r.run_id for r in results}),
    )
    return {"suite_health": health}


# --------------------------------------------------------------------------- #
# review — HITL human node (L2 only) (spec §2.2)
# --------------------------------------------------------------------------- #
def review(state: AgentState) -> dict:
    """Analyst confirms/filters findings before persistence (L2 only).

    Pauses the graph with ``interrupt()``, surfacing the current flaky tests and failure
    clusters for the analyst. Resuming with ``Command(resume=<decisions>)`` delivers the
    analyst's choices (``{"dismissed_flaky": [...], "dismissed_clusters": [...]}``) which
    ``synthesis`` then honours. Under L1/L3 the conditional edge in graph.py skips this node,
    so ``interrupt()`` is never reached.
    """
    from langgraph.types import interrupt  # lazy: package stays importable without langgraph

    flaky = [f for f in state.get("flaky_findings", []) if f.verdict == "flaky"]
    payload = {
        "flaky": [
            {"test_id": f.test_id, "flakiness_score": f.flakiness_score,
             "pass_count": f.pass_count, "fail_count": f.fail_count,
             "runs_observed": f.runs_observed}
            for f in flaky
        ],
        "clusters": [
            {"cluster_id": c.cluster_id, "label": c.label,
             "signature": c.signature, "count": c.count}
            for c in state.get("failure_clusters", [])
        ],
    }
    decision = interrupt(payload)              # ← pauses here under L2
    return {"review_decisions": decision or {}}


# --------------------------------------------------------------------------- #
# synthesis now lives in nodes/synthesis.py (ranking + grounded recommendations).
# persist now lives in nodes/persist.py (MongoDB run store / local JSON fallback).
# --------------------------------------------------------------------------- #
