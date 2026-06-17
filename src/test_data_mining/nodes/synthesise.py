"""
synthesise.py — Assemble the final dataset from the analyst's chosen sets (pivot §10, G5).

Type: deterministic (+ optional Gemini narrative). For each included field it takes the chosen
candidate set's values (or the analyst's custom values), aligns them into rows, and emits
``final_dataset`` (rows shaped like the canonical CSV, with `scenario_tag` + `data_category`) plus
a ``report`` (row count, source mix, gaps filled, recommendations).

If a field has no explicit selection it falls back to the widest-coverage set, so the node also
works for non-UI/auto resumes.
"""
from __future__ import annotations

from collections import Counter

from ..state import AgentState, CandidateSet, FieldCandidates, ReviewSelection

_MAX_ROWS = 20


def _chosen_set(fc: FieldCandidates, sel: ReviewSelection | None) -> CandidateSet | None:
    if sel and sel.chosen_set_id:
        for s in fc.sets:
            if s.set_id == sel.chosen_set_id:
                return s
    return max(fc.sets, key=lambda s: len(s.scenario_coverage)) if fc.sets else None


def synthesise(state: AgentState, llm=None) -> dict:
    """LangGraph node: build final_dataset rows + a summary report from the chosen sets."""
    cands = {fc.field_name: fc for fc in state.get("candidate_sets", [])}
    sels = {s.field_name: s for s in state.get("review_selections", [])}

    chosen: dict[str, tuple[list, str, list[str]]] = {}   # field -> (values, source, coverage)
    excluded: list[str] = []
    for name, fc in cands.items():
        sel = sels.get(name)
        if sel is not None and not sel.include:
            excluded.append(name)
            continue
        if sel and sel.custom_values:
            chosen[name] = (list(sel.custom_values), "custom", ["custom"])
            continue
        cs = _chosen_set(fc, sel)
        if cs and cs.values:
            chosen[name] = (list(cs.values), cs.source, cs.scenario_coverage)
        else:
            excluded.append(name)

    columns = list(chosen.keys())
    n = min(max((len(v) for v, _s, _c in chosen.values()), default=0), _MAX_ROWS)
    rows: list[dict] = []
    for i in range(n):
        row = {name: vals[i % len(vals)] for name, (vals, _s, _c) in chosen.items()}
        row["scenario_tag"] = f"generated_{i + 1:03d}"
        row["data_category"] = "generated"
        rows.append(row)

    # source mix (by field) + which fields filled a coverage gap
    mix = Counter(src for _v, src, _c in chosen.values())
    total = sum(mix.values()) or 1
    source_mix = {k: round(100 * v / total) for k, v in mix.items()}
    gaps_filled = [name for name, (_v, _s, cov) in chosen.items()
                   if any(t in ("boundary", "negative", "edge") for t in cov)]

    recs: list[str] = []
    reused = [n_ for n_, (_v, s, _c) in chosen.items() if s in ("existing", "retrieved")]
    if reused:
        recs.append(f"Reused stored values for {len(reused)} field(s): {', '.join(reused[:5])}.")
    if gaps_filled:
        recs.append(f"Filled coverage gaps for {len(gaps_filled)} field(s): {', '.join(gaps_filled[:5])}.")
    if excluded:
        recs.append(f"Excluded {len(excluded)} field(s) per review: {', '.join(excluded[:5])}.")
    if not recs:
        recs.append("Dataset assembled from the selected sets.")

    summary = f"{len(rows)} rows across {len(columns)} fields; source mix {source_mix}."
    if llm is not None:
        try:
            narrated = llm(f"Write one concise sentence summarising a generated test dataset: "
                           f"{len(rows)} rows, {len(columns)} fields, source mix {source_mix}, "
                           f"{len(gaps_filled)} gap-filling fields. No preamble.").strip()
            if narrated:
                summary = narrated
        except Exception:
            pass

    report = {
        "summary": summary,
        "row_count": len(rows),
        "columns": columns + ["scenario_tag", "data_category"],
        "source_mix_pct": source_mix,
        "gaps_filled_fields": gaps_filled,
        "fields_excluded": excluded,
        "coverage_gaps_total": len(state.get("coverage_gaps", [])),
        "recommendations": recs,
    }
    print(f"NODE_EXIT synthesise: {len(rows)} rows, {len(columns)} fields, mix {source_mix}")
    return {"final_dataset": rows, "report": report}
