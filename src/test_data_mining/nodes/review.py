"""
review.py — Set-based HITL gate (pivot §5). ALWAYS runs (this agent is L2-only).

Pauses the graph with ``interrupt()``, surfacing each field's candidate value SETS so the analyst
can pick ONE per field (or exclude it). Resuming with
``Command(resume={"review_selections": [...]})`` maps the choices into `review_selections`, which
`synthesise` then honours.
"""
from __future__ import annotations

from ..state import AgentState, FieldCandidates, ReviewSelection


def build_payload(candidate_sets: list[FieldCandidates]) -> dict:
    """The per-field interrupt payload the frontend renders as radio-set rows."""
    # Called by review() before interrupt() to present choices to the analyst.
    # Output example: {"fields": [{"field_name":"email","category":"Identity",...}]}.
    return {
        "fields": [
            {
                "field_name": fc.field_name,
                "category": fc.category,
                "gap_flagged": fc.gap_flagged,
                "sets": [
                    {"set_id": s.set_id, "source": s.source, "values": s.values,
                     "scenario_coverage": s.scenario_coverage, "note": s.note}
                    for s in fc.sets
                ],
            }
            for fc in candidate_sets
        ]
    }


def auto_selections(candidate_sets: list[FieldCandidates]) -> list[dict]:
    """Default choice (widest scenario coverage per field) — used to drive non-UI resumes/tests."""
    # This helper is used by automated resume/test harnesses when no analyst decision is supplied.
    # Output example: [{"field_name":"email","include":True,"chosen_set_id":"gen_A"}]
    out = []
    for fc in candidate_sets:
        if not fc.sets:
            continue
        best = max(fc.sets, key=lambda s: len(s.scenario_coverage))
        out.append({"field_name": fc.field_name, "include": True, "chosen_set_id": best.set_id})
    return out


def _to_selections(decision) -> list[ReviewSelection]:
    # Accept either the interrupt return payload or a direct resume dict.
    raw = decision.get("review_selections", []) if isinstance(decision, dict) else (decision or [])
    selections = []
    for r in raw:
        selections.append(ReviewSelection(
            field_name=r["field_name"],
            include=bool(r.get("include", True)),
            chosen_set_id=r.get("chosen_set_id"),
            custom_values=r.get("custom_values"),
        ))
    return selections


def review(state: AgentState) -> dict:
    """LangGraph node: pause for the analyst, then record their set selections."""
    from langgraph.types import interrupt  # lazy: package importable without langgraph

    decision = interrupt(build_payload(state.get("candidate_sets", [])))
    # `interrupt()` returns the analyst decision payload; normalize it to ReviewSelection objects.
    return {"review_selections": _to_selections(decision)}
