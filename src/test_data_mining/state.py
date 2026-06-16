"""
state.py — The shared state contract for the Test Data Mining Agent.

Every LangGraph node receives an ``AgentState`` and returns a dict of the keys it
updated. This module is the single source of truth for what flows through the graph.

Design rules (see CLAUDE.md):
  * Deterministic detectors populate `flaky_findings`, `coverage_findings`,
    `failure_clusters`, and `suite_health` independently and in parallel.
  * The LLM only writes `cluster_labels` (inside failure_clustering) and the final `report`.
  * `errors` / `gaps` collect graceful-degradation notes — nodes append, never crash.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Enums / config
# --------------------------------------------------------------------------- #
class AutonomyLevel(str, Enum):
    L1_ASSISTIVE = "L1"      # one-shot, no review gate
    L2_SUPERVISED = "L2"     # full pipeline + HITL review before persist (DEFAULT)
    L3_GOAL_DRIVEN = "L3"    # full pipeline, persists without review


TestOutcome = Literal["passed", "failed", "skipped", "error"]


# --------------------------------------------------------------------------- #
# Normalised data records (ingest writes these)
# --------------------------------------------------------------------------- #
@dataclass
class TestResult:
    """One test outcome from one run, normalised across all source formats."""
    __test__ = False                  # not a pytest test class (name starts with "Test")
    test_id: str                      # fully-qualified test name (stable key)
    suite: str
    outcome: TestOutcome
    duration_sec: float
    run_id: str
    commit_sha: str                   # used to group "same-version" runs for flaky detection
    timestamp: str                    # ISO 8601
    message: Optional[str] = None     # failure/error message (raw)
    stack_trace: Optional[str] = None
    source_format: str = "junit"      # "junit" | "playwright" | ...


@dataclass
class FlakyFinding:
    test_id: str
    flakiness_score: float            # 0.0 (stable) .. 1.0 (maximally flaky)
    runs_observed: int
    pass_count: int
    fail_count: int
    last_failure_ts: Optional[str]
    verdict: Literal["flaky", "stable", "insufficient_history"]


@dataclass
class CoverageFinding:
    module: str
    coverage_pct: float
    status: Literal["ok", "low", "missing", "declining"]


@dataclass
class FailureCluster:
    cluster_id: str
    signature: str                    # normalised error signature
    count: int
    representative_trace: str
    label: Optional[str] = None       # LLM-generated; None until synthesis/labelling runs


@dataclass
class SuiteHealth:
    pass_rate: float
    mean_duration_sec: float
    flake_rate: float
    window_runs: int


# --------------------------------------------------------------------------- #
# The graph state
# --------------------------------------------------------------------------- #
class AgentState(TypedDict, total=False):
    # --- inputs / config ---
    input_path: str                          # where source files live
    autonomy_level: AutonomyLevel
    min_runs_for_flaky: int                  # N — minimum history for flaky detection
    flaky_score_cutoff: float                # score >= cutoff => "flaky"
    min_minority_fails: int                  # minority outcome must appear >= this many times

    # --- ingest / validate ---
    raw_results: list[TestResult]            # normalised test outcomes across all runs
    validation_ok: bool

    # --- parallel detectors ---
    flaky_findings: list[FlakyFinding]
    coverage_findings: list[CoverageFinding]
    failure_clusters: list[FailureCluster]
    suite_health: Optional[SuiteHealth]

    # --- HITL ---
    review_decisions: dict[str, Any]         # analyst filter/confirm choices (L2)

    # --- synthesis / output ---
    report: Optional[dict[str, Any]]         # final prioritised report (persisted)

    # --- graceful degradation (append-only; never crash) ---
    # operator.add reducers make every node's return APPEND to these lists instead of
    # overwriting, and let the parallel detector fan-out write them concurrently without
    # a LangGraph InvalidUpdateError. A node that has nothing to add returns [] (a no-op).
    gaps: Annotated[list[str], operator.add]     # explicit "we couldn't compute X" notes
    errors: Annotated[list[str], operator.add]   # NODE_ERROR notes


def initial_state(
    input_path: str,
    autonomy_level: AutonomyLevel = AutonomyLevel.L2_SUPERVISED,
    min_runs_for_flaky: int = 5,
    flaky_score_cutoff: float = 0.2,
    min_minority_fails: int = 2,
) -> AgentState:
    """Build a fresh state with sane defaults from the spec."""
    return AgentState(
        input_path=input_path,
        autonomy_level=autonomy_level,
        min_runs_for_flaky=min_runs_for_flaky,
        flaky_score_cutoff=flaky_score_cutoff,
        min_minority_fails=min_minority_fails,
        raw_results=[],
        validation_ok=False,
        flaky_findings=[],
        coverage_findings=[],
        failure_clusters=[],
        suite_health=None,
        review_decisions={},
        report=None,
        gaps=[],
        errors=[],
    )
