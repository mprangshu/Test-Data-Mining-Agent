"""
coverage_gap.py — Find untested field × scenario-type combinations (pivot §10).

Type: deterministic. Builds the matrix ``required fields × {valid, boundary, negative, edge}``
(each field's required scenarios come from `parsed_fields`), subtracts what the result files
actually exercised (`result_signals`), and reports the remainder as `coverage_gaps`. A scenario
that *ran but failed* still counts as exercised (it was tested) — coverage is about whether a
combination was tried, not whether it passed.
"""
from __future__ import annotations

from ..state import AgentState, CoverageGap

_ALL_SCENARIOS = ["valid", "boundary", "negative", "edge"]


def coverage_gap(state: AgentState) -> dict:
    """LangGraph node: list field × scenario-type combinations never exercised."""
    fields = state.get("parsed_fields", [])
    signals = state.get("result_signals", [])

    exercised: set[tuple[str, str]] = set()
    for s in signals:
        for fld in s.fields_exercised:
            exercised.add((fld, s.scenario_type))

    gaps: list[CoverageGap] = []
    for f in fields:
        required = f.scenario_types or _ALL_SCENARIOS
        for stype in required:
            if (f.name, stype) not in exercised:
                gaps.append(CoverageGap(
                    field_name=f.name,
                    scenario_type=stype,
                    reason=f"no {stype}-scenario value exercised for '{f.name}'",
                ))

    print(f"NODE_EXIT coverage_gap: {len(gaps)} gaps across {len(fields)} fields")
    return {"coverage_gaps": gaps}
