"""
Stub nodes for the Test Data Mining Agent.

These are deliberately minimal so Claude Code has clear rails to fill in. Each function
already has the right signature and returns the right state keys — implement the body per
the referenced spec section. The deterministic core (ingest, flaky_detect) is already real;
build these in ROADMAP order.

KEEP THE INVARIANTS (see CLAUDE.md): read-only, no Neo4j, deterministic detectors before LLM.
"""
from __future__ import annotations

from collections import defaultdict

from ..state import AgentState, SuiteHealth


# --------------------------------------------------------------------------- #
# validate — deterministic (spec §2.3)
# --------------------------------------------------------------------------- #
def validate(state: AgentState) -> dict:
    """Quality gates: flag corrupt/insufficient data; set validation_ok.

    TODO:
      * mark validation_ok = False (and append to gaps) when raw_results is empty.
      * detect runs with too little history for flaky detection and note it.
      * keep going on partial data — never raise (graceful degradation, spec §1.4).
    """
    results = state.get("raw_results", [])
    ok = len(results) > 0
    gaps = [] if ok else ["validate: no parseable results found"]
    print(f"NODE_EXIT validate: validation_ok={ok}, {len(results)} results")
    return {"validation_ok": ok, "gaps": gaps}


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
# failure_clustering — vector + LLM (spec §2.3, §2.6, G3)
# --------------------------------------------------------------------------- #
def failure_clustering(state: AgentState) -> dict:
    """Group failures by root-cause signature.

    TODO (spec §2.6 — vector DB, NOT a graph DB):
      1. Collect failure messages+stacks from raw_results where outcome in (failed, error).
      2. Normalise each (strip line numbers, addresses, timestamps) -> signature string.
      3. Embed signatures and cluster by cosine similarity in ChromaDB (threshold/HDBSCAN).
      4. LLM labels each cluster (optionally RAG-grounded on past resolved failures).
         -> the LLM only LABELS clusters; the vector DB FORMS them.

    A trivial deterministic placeholder (exact-signature grouping) is below so the pipeline
    runs end-to-end before ChromaDB is wired in. Replace with real embedding clustering.
    """
    results = state.get("raw_results", [])
    buckets: dict[str, list] = defaultdict(list)
    for r in results:
        if r.outcome in ("failed", "error") and r.message:
            buckets[r.message.strip()].append(r)

    from ..state import FailureCluster
    clusters = [
        FailureCluster(
            cluster_id=f"c{i:03d}",
            signature=sig,
            count=len(rows),
            representative_trace=(rows[0].stack_trace or ""),
            label=None,  # filled by LLM later
        )
        for i, (sig, rows) in enumerate(sorted(buckets.items(), key=lambda kv: -len(kv[1])))
    ]
    print(f"NODE_EXIT failure_clustering: {len(clusters)} placeholder clusters (replace w/ ChromaDB)")
    return {"failure_clusters": clusters}


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
    """Analyst confirms/filters findings before persistence (L2).

    TODO: implement with LangGraph interrupt():
        from langgraph.types import interrupt, Command
        decision = interrupt({"flaky": state["flaky_findings"], ...})
        # resume delivers the analyst's filter choices into review_decisions
    Under L1/L3 this node is skipped by the conditional edge in graph.py.
    """
    return {"review_decisions": state.get("review_decisions", {})}


# --------------------------------------------------------------------------- #
# synthesis — LLM (spec §2.3, G5)
# --------------------------------------------------------------------------- #
def synthesis(state: AgentState) -> dict:
    """Rank findings + write prioritised recommendations via the Hub LLM router.

    TODO:
      * call the Hub Python LLM router (Anthropic default) — never a standalone key.
      * input: flaky_findings + coverage_findings + failure_clusters + suite_health
               (after review filtering under L2).
      * output: a structured report dict (ranked findings + human-readable recommendations).
      * verify any LLM-claimed root cause against raw data before including it (anti-hallucination).
    """
    report = {
        "flaky": [f.test_id for f in state.get("flaky_findings", []) if f.verdict == "flaky"],
        "clusters": [{"signature": c.signature, "count": c.count}
                     for c in state.get("failure_clusters", [])],
        "suite_health": state.get("suite_health"),
        "recommendations": ["TODO: LLM-generated prioritised recommendations"],
    }
    print("NODE_EXIT synthesis: placeholder report assembled (wire LLM router)")
    return {"report": report}


# --------------------------------------------------------------------------- #
# persist — deterministic (spec §2.3)
# --------------------------------------------------------------------------- #
def persist(state: AgentState) -> dict:
    """Persist the report to the run store (MongoDB).

    TODO: write state["report"] to the MongoDB run store via the platform's persistence
    layer. NO Neo4j, NO KG_SIGNAL_* events. For local dev you may dump JSON to data/reports/.
    """
    print("NODE_EXIT persist: TODO write report to MongoDB run store")
    return {}
