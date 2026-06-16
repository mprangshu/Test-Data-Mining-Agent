"""
graph.py — LangGraph StateGraph wiring for the Test Data Mining Agent.

Topology (spec §2.2):

    ingest -> validate -> [ flaky_detect | coverage_gap | failure_clustering ]  (parallel)
           -> suite_health -> (review if L2) -> synthesis -> persist

Conditional routing: the `review` HITL node runs only under L2; L1/L3 route straight to
`synthesis`.

This module requires `langgraph` (see requirements.txt). The nodes it wires are already
importable; the LLM-dependent ones are placeholders until built out (see docs/ROADMAP.md).
"""
from __future__ import annotations

import argparse

from .state import AgentState, AutonomyLevel, initial_state
from .nodes.ingest import ingest
from .nodes.flaky_detect import flaky_detect
from .nodes.failure_clustering import failure_clustering
from .nodes.synthesis import synthesis
from .nodes.persist import persist
from .nodes.stubs import (
    validate,
    coverage_gap,
    suite_health,
    review,
)


def _route_after_health(state: AgentState) -> str:
    """L2 goes through the human review gate; L1/L3 skip straight to synthesis."""
    return "review" if state.get("autonomy_level") == AutonomyLevel.L2_SUPERVISED else "synthesis"


def build_graph(checkpointer=None):
    """Construct and compile the agent graph.

    Imported lazily so the rest of the package (parsers, detectors, tests) works without
    langgraph installed.
    """
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AgentState)
    g.add_node("ingest", ingest)
    g.add_node("validate", validate)
    g.add_node("flaky_detect", flaky_detect)
    g.add_node("coverage_gap", coverage_gap)
    g.add_node("failure_clustering", failure_clustering)
    g.add_node("suite_health", suite_health)
    g.add_node("review", review)
    g.add_node("synthesis", synthesis)
    g.add_node("persist", persist)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "validate")

    # Fan out to the three deterministic/vector detectors in parallel.
    for detector in ("flaky_detect", "coverage_gap", "failure_clustering"):
        g.add_edge("validate", detector)
        g.add_edge(detector, "suite_health")   # fan-in barrier

    # Conditional HITL gate.
    g.add_conditional_edges("suite_health", _route_after_health,
                            {"review": "review", "synthesis": "synthesis"})
    g.add_edge("review", "synthesis")
    g.add_edge("synthesis", "persist")
    g.add_edge("persist", END)

    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Test Data Mining Agent over fixtures.")
    ap.add_argument("--input", default="data/fixtures", help="path to run_* fixtures")
    ap.add_argument("--autonomy", default="L2", choices=["L1", "L2", "L3"])
    args = ap.parse_args()

    state = initial_state(args.input, autonomy_level=AutonomyLevel(args.autonomy))
    graph = build_graph()
    config = {"configurable": {"thread_id": "local-run"}}
    result = graph.invoke(state, config=config)
    print("\n=== REPORT ===")
    print(result.get("report"))


if __name__ == "__main__":
    main()
