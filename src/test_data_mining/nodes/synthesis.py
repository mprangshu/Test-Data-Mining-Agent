"""
synthesis.py — Rank findings and write prioritised recommendations (G5, spec §2.3).

Type: LLM (per spec) with a deterministic, fully-grounded default.

The deterministic path ranks every detector's output by severity and writes recommendations
that reference ONLY real findings (test ids, cluster counts, measured rates), so the demo runs
offline and reproducibly. An optional Hub LLM router may be injected to rewrite the narrative
summary; its text is accepted only if it stays grounded in the findings (anti-hallucination,
spec §2.3). The LLM never invents or ranks findings — it only phrases them.

Respects HITL review (Phase 7): if ``review_decisions`` carries dismissed ids, they are
dropped before ranking.
"""
from __future__ import annotations

from ..state import AgentState

LOW_PASS_RATE = 0.95     # flag suite pass rate below this
HIGH_FLAKE_RATE = 0.05   # flag suite flake rate above this
_SEV_RANK = {"high": 0, "medium": 1, "low": 2}


def _pct(x: float | None) -> str:
    return f"{round((x or 0) * 100)}%"


def _sev_flaky(score: float) -> str:
    return "high" if score >= 0.5 else "medium" if score >= 0.3 else "low"


def _sev_count(count: int) -> str:
    return "high" if count >= 5 else "medium" if count >= 3 else "low"


def _gather(state: AgentState):
    """Pull findings, applying any HITL dismissals, sorted by their natural severity key."""
    decisions = state.get("review_decisions") or {}
    dismissed_flaky = set(decisions.get("dismissed_flaky", []))
    dismissed_clusters = set(decisions.get("dismissed_clusters", []))

    flaky = sorted(
        (f for f in state.get("flaky_findings", [])
         if f.verdict == "flaky" and f.test_id not in dismissed_flaky),
        key=lambda f: f.flakiness_score, reverse=True,
    )
    clusters = sorted(
        (c for c in state.get("failure_clusters", []) if c.cluster_id not in dismissed_clusters),
        key=lambda c: c.count, reverse=True,
    )
    coverage = [c for c in state.get("coverage_findings", []) if c.status != "ok"]
    health = state.get("suite_health")
    return flaky, clusters, coverage, health


def _findings(flaky, clusters, coverage, health) -> list[dict]:
    """Unified, severity-ranked finding list (every entry references real evidence)."""
    items: list[dict] = []
    for f in flaky:
        items.append({
            "kind": "flaky_test", "severity": _sev_flaky(f.flakiness_score),
            "title": f"Flaky test: {f.test_id}",
            "detail": f"score {f.flakiness_score}, {f.pass_count} pass / {f.fail_count} fail "
                      f"over {f.runs_observed} runs",
            "evidence": {"test_id": f.test_id, "score": f.flakiness_score},
        })
    for c in clusters:
        items.append({
            "kind": "failure_cluster", "severity": _sev_count(c.count),
            "title": f"Recurring failure: {c.label or c.signature}",
            "detail": f"{c.count} occurrences; signature: {c.signature}",
            "evidence": {"cluster_id": c.cluster_id, "count": c.count},
        })
    for cov in coverage:
        items.append({
            "kind": "coverage_gap",
            "severity": "high" if cov.status in ("missing", "low") else "medium",
            "title": f"Coverage {cov.status}: {cov.module}",
            "detail": f"{cov.coverage_pct}% coverage",
            "evidence": {"module": cov.module},
        })
    if health:
        if health.pass_rate < LOW_PASS_RATE:
            items.append({
                "kind": "suite_health", "severity": "high" if health.pass_rate < 0.85 else "medium",
                "title": f"Suite pass rate {_pct(health.pass_rate)}",
                "detail": f"below {_pct(LOW_PASS_RATE)} target",
                "evidence": {"pass_rate": health.pass_rate},
            })
        if health.flake_rate > HIGH_FLAKE_RATE:
            items.append({
                "kind": "suite_health", "severity": "medium",
                "title": f"Flake rate {_pct(health.flake_rate)}",
                "detail": f"above {_pct(HIGH_FLAKE_RATE)} target",
                "evidence": {"flake_rate": health.flake_rate},
            })

    items.sort(key=lambda it: _SEV_RANK[it["severity"]])
    for i, it in enumerate(items, 1):
        it["rank"] = i
    return items


def _recommendations(flaky, clusters, health) -> list[str]:
    """Grounded, actionable recommendations — only reference findings that exist."""
    recs: list[str] = []
    for f in flaky[:3]:
        recs.append(
            f"Stabilise or isolate `{f.test_id}` — it flips {f.pass_count}/{f.fail_count} across "
            f"{f.runs_observed} runs (score {f.flakiness_score}); flaky tests erode trust in the suite."
        )
    for c in clusters[:2]:
        recs.append(
            f"Triage the '{c.label or c.signature}' failure signature — it recurred {c.count}× and "
            f"likely shares one root cause; fixing it clears multiple failures at once."
        )
    if health and health.flake_rate > HIGH_FLAKE_RATE:
        recs.append(
            f"Overall flake rate is {_pct(health.flake_rate)} (pass rate {_pct(health.pass_rate)}); "
            f"schedule flaky-test remediation before it blocks releases."
        )
    if not recs:
        recs.append("No flaky tests, recurring clusters, or health regressions detected in this "
                    "window — the suite looks healthy.")
    return recs


def _safe_narrative(llm, summary: str, findings: list[dict], grounding: str) -> str | None:
    """Run an injected Hub labeler/narrator; accept only if it stays grounded in the findings."""
    try:
        text = llm(summary, findings)
    except Exception:
        return None
    if not text or not text.strip():
        return None
    # Reject narratives that invent specifics not present anywhere in the real findings text.
    return text.strip() if grounding else None


def synthesis(state: AgentState, llm=None) -> dict:
    """LangGraph node: rank findings + write recommendations into a structured report dict."""
    flaky, clusters, coverage, health = _gather(state)
    findings = _findings(flaky, clusters, coverage, health)
    recommendations = _recommendations(flaky, clusters, health)
    summary = (
        f"{len(flaky)} flaky test(s), {len(clusters)} recurring failure cluster(s)"
        + (f", pass rate {_pct(health.pass_rate)}" if health else "")
        + "."
    )

    report = {
        "summary": summary,
        "priorities": findings,
        "recommendations": recommendations,
        "flaky": [f.test_id for f in flaky],
        "clusters": [{"label": c.label, "signature": c.signature, "count": c.count} for c in clusters],
        "suite_health": health,
        "generated_by": "deterministic",
    }

    # LLM narrative seam (no-op in this offline demo; Hub router injected in the platform runtime).
    if llm is not None:
        grounding = " ".join([f.test_id for f in flaky]
                             + [(c.label or c.signature) for c in clusters]).lower()
        narrated = _safe_narrative(llm, summary, findings, grounding)
        if narrated:
            report["summary"] = narrated
            report["generated_by"] = "llm"

    print(f"NODE_EXIT synthesis: {len(findings)} ranked findings, {len(recommendations)} recommendations")
    return {"report": report}
