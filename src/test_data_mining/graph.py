"""
graph.py — LangGraph StateGraph wiring for the Test Data Mining Agent (v2).

Topology (pivot §3):

    parse → [ load_results | mongo_lookup | vector_search ]   (parallel after parse)
          → coverage_gap → generate → review (HITL, ALWAYS) → synthesise → persist

`coverage_gap` depends on `load_results`; `generate` fans in from coverage_gap + mongo_lookup +
vector_search. `review` always interrupts (L2-only) — resume via `Command(resume=...)`.
"""
from __future__ import annotations

import argparse
import logging

# Our state dataclasses round-trip through the MemorySaver checkpoint fine; LangGraph just emits a
# forward-compat advisory about serializing unregistered types. Quiet that known-safe noise.
logging.getLogger("langgraph.checkpoint.serde.jsonplus").setLevel(logging.ERROR)

from .state import AgentState, initial_state
from .nodes.parse import parse
from .nodes.load_results import load_results
from .nodes.mongo_lookup import mongo_lookup
from .nodes.vector_search import vector_search
from .nodes.coverage_gap import coverage_gap
from .nodes.generate import generate
from .nodes.review import review, auto_selections
from .nodes.synthesise import synthesise
from .nodes.persist import persist


def build_graph(checkpointer=None):
    """Construct and compile the agent graph (lazy langgraph import)."""
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AgentState)
    for name, fn in [
        ("parse", parse), ("load_results", load_results), ("mongo_lookup", mongo_lookup),
        ("vector_search", vector_search), ("coverage_gap", coverage_gap), ("generate", generate),
        ("review", review), ("synthesise", synthesise), ("persist", persist),
    ]:
        g.add_node(name, fn)

    # Sequential data-gather. (The nodes are independent and could fan out in parallel, but a
    # staggered multi-parent fan-in into `generate` interacts badly with the downstream
    # `interrupt()` on resume — re-running upstream nodes. A single-parent chain keeps the HITL
    # interrupt/resume clean; the data volumes here make the sequential cost negligible.)
    g.add_edge(START, "parse")
    g.add_edge("parse", "load_results")
    g.add_edge("load_results", "mongo_lookup")
    g.add_edge("mongo_lookup", "vector_search")
    g.add_edge("vector_search", "coverage_gap")
    g.add_edge("coverage_gap", "generate")
    g.add_edge("generate", "review")          # HITL gate — always interrupts
    g.add_edge("review", "synthesise")
    g.add_edge("synthesise", "persist")
    g.add_edge("persist", END)

    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the Test Data Mining Agent (v2) over inputs.")
    ap.add_argument("--input", default="data/sample_upload",
                    help="dir with test_cases/ (and optional results/)")
    args = ap.parse_args()

    from langgraph.types import Command

    graph = build_graph()
    config = {"configurable": {"thread_id": "local-run"}}
    graph.invoke(initial_state(args.input), config=config)

    # The graph pauses at the review gate; for a non-interactive CLI run, auto-select and resume.
    snap = graph.get_state(config)
    if snap.next:
        cands = snap.values.get("candidate_sets", [])
        print(f"\n[review gate] auto-selecting widest-coverage set for {len(cands)} fields…")
        graph.invoke(Command(resume={"review_selections": auto_selections(cands)}), config=config)

    final = graph.get_state(config).values
    report = final.get("report") or {}
    print("\n=== REPORT ===")
    print(report.get("summary"))
    print("recommendations:", report.get("recommendations"))
    print("rows:", report.get("row_count"), "columns:", report.get("columns"))


if __name__ == "__main__":
    main()
