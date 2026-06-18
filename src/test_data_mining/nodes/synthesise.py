"""
synthesise.py — Assemble the final dataset (pivot §10, G5; fixed per docs/IMPROVEMENT.md, Phase 9).

Type: deterministic (+ optional Gemini for coherent whole-row generation).

The agent is **additive and schema-agnostic** (CLAUDE.md invariants #7–10):

  final_dataset = original uploaded rows (VERBATIM)  +  newly generated rows

* **Always larger** — ``len(final_dataset) > input_row_count`` is asserted; the optional
  ``EXPANSION_FACTOR`` aims for ~3× input but the only hard rule is *more rows out than in*.
* **Schema-agnostic** — output columns are exactly ``state["input_columns"]`` (any count/names,
  preserved in order). Never hardcode a column; never add one the input didn't have.
* **Honest tagging** — ``scenario_tag``/``data_category`` are written on NEW rows **only if** those
  columns exist in the upload, tagged by real scenario type (never ``generated_NNN``).
* **Coherent** — when an LLM is available each new row is generated *whole* so cross-field
  relationships hold; offline it falls back to per-column assembly from the chosen sets.

If a field has no explicit selection it falls back to the widest-coverage set, so the node also
works for non-UI/auto resumes.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from ..state import AgentState, CandidateSet, FieldCandidates, ReviewSelection

# Optional, tunable: aim for ~EXPANSION_FACTOR× the input. The HARD rule is only output > input.
EXPANSION_FACTOR = 3
_SCENARIOS = ["valid", "boundary", "negative", "edge"]
_TAG_COL, _CAT_COL = "scenario_tag", "data_category"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _chosen_set(fc: FieldCandidates, sel: ReviewSelection | None) -> CandidateSet | None:
    if sel and sel.chosen_set_id:
        for s in fc.sets:
            if s.set_id == sel.chosen_set_id:
                return s
    return max(fc.sets, key=lambda s: len(s.scenario_coverage)) if fc.sets else None


def _scenario_sequence(state: AgentState, n: int) -> list[str]:
    """Which scenario type each new row targets. Mode A (results present) steers toward the
    untested scenario types from `coverage_gaps`; Mode B (no results) spreads evenly."""
    gap_types = [g.scenario_type for g in state.get("coverage_gaps", [])]
    weights = [s for s in _SCENARIOS if s in set(gap_types)] or _SCENARIOS
    return [weights[i % len(weights)] for i in range(n)]


def _strip_fences(text: str) -> str:
    return _FENCE.sub("", text.strip())


def _llm_rows_by_type(llm, columns, sample_real, counts: dict[str, int]) -> dict[str, list[dict]]:
    """Best-effort: ask the LLM for whole, internally-consistent rows per scenario type."""
    out: dict[str, list[dict]] = {}
    for stype, need in counts.items():
        rows: list[dict] = []
        try:
            prompt = (
                f"Generate {need} realistic test-data rows as a JSON array of objects. "
                f"Each object MUST have EXACTLY these keys: {columns}. "
                f"Scenario type: {stype} (valid=happy path; boundary=limits/extremes; "
                f"negative=invalid/rejected; edge=unusual-but-possible). "
                f"Use these real example rows to infer realistic values AND cross-column "
                f"relationships, keeping every row internally consistent: {sample_real}. "
                f"Return ONLY the JSON array — no prose, no markdown fences."
            )
            data = json.loads(_strip_fences(llm(prompt)))
            src = data if isinstance(data, list) else [data]
            rows = [{c: r.get(c, "") for c in columns} for r in src if isinstance(r, dict)]
        except Exception:
            rows = []
        out[stype] = rows
    return out


def _det_row(columns, chosen, passthrough, i: int) -> dict:
    """Per-column deterministic row (offline / LLM-shortfall fallback). Cross-field coherence is
    best-effort: chosen-set values by index, other input columns sampled from the originals."""
    row = {}
    for col in columns:
        if col in (_TAG_COL, _CAT_COL):
            continue                              # set by the caller (honest scenario tag)
        if col in chosen:
            vals = chosen[col][0]
            row[col] = vals[i % len(vals)] if vals else ""
        else:                                     # excluded / unknown column → reuse a real value
            pv = passthrough.get(col) or []
            row[col] = pv[i % len(pv)] if pv else ""
    return row


def synthesise(state: AgentState, llm=None) -> dict:
    """LangGraph node: original rows (verbatim) + generated rows; schema-agnostic, always larger."""
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

    # Output columns are the UPLOAD's columns (schema-agnostic). With no tabular upload (e.g. a
    # Gherkin .txt only), fall back to the chosen field names.
    input_rows = list(state.get("input_rows", []))        # originals — pass through UNCHANGED
    input_n = state.get("input_row_count", len(input_rows))
    field_columns = list(chosen.keys())
    out_columns = list(state.get("input_columns", [])) or field_columns

    has_tag = _TAG_COL in out_columns
    has_cat = _CAT_COL in out_columns

    # always larger: at least one new row; default aims for ~EXPANSION_FACTOR× the input
    new_target = max(1, (EXPANSION_FACTOR - 1) * max(input_n, 1))
    seq = _scenario_sequence(state, new_target)

    # real example rows to anchor realism (originals if we have them, else one row of chosen values)
    if input_rows:
        sample_real = input_rows[:3]
    else:
        sample_real = [{c: (chosen[c][0][0] if chosen.get(c) and chosen[c][0] else "")
                        for c in field_columns}] if field_columns else []
    passthrough = {c: [r[c] for r in input_rows if str(r.get(c, "")).strip()] for c in out_columns}

    llm_rows = {}
    if llm is not None and out_columns:
        llm_rows = _llm_rows_by_type(llm, out_columns, sample_real, dict(Counter(seq)))
    cursor = Counter()                            # how many of each stype's llm rows we've consumed

    new_rows: list[dict] = []
    for i, stype in enumerate(seq):
        pool = llm_rows.get(stype, [])
        k = cursor[stype]
        if k < len(pool) and pool[k]:
            row = dict(pool[k])
        else:
            row = _det_row(out_columns, chosen, passthrough, i)
        cursor[stype] += 1
        if has_tag:
            row[_TAG_COL] = f"{stype}_{i + 1:03d}"
        if has_cat:
            row[_CAT_COL] = stype
        if out_columns:                           # enforce the exact uploaded column set
            row = {c: row.get(c, "") for c in out_columns}
        new_rows.append(row)

    final_dataset = input_rows + new_rows         # ADDITIVE: originals first, generated appended
    if out_columns:
        assert len(final_dataset) > input_n, "REGRESSION: output not larger than input"

    # source mix (by field) + which fields filled a coverage gap
    mix = Counter(src for _v, src, _c in chosen.values())
    total = sum(mix.values()) or 1
    source_mix = {k: round(100 * v / total) for k, v in mix.items()}
    gaps_filled = [name for name, (_v, _s, cov) in chosen.items()
                   if any(t in ("boundary", "negative", "edge") for t in cov)]

    recs: list[str] = []
    recs.append(f"Additive output: {input_n} original row(s) preserved + {len(new_rows)} generated "
                f"= {len(final_dataset)} total.")
    reused = [n_ for n_, (_v, s, _c) in chosen.items() if s in ("existing", "retrieved")]
    if reused:
        recs.append(f"Reused stored values for {len(reused)} field(s): {', '.join(reused[:5])}.")
    if gaps_filled:
        recs.append(f"Filled coverage gaps for {len(gaps_filled)} field(s): {', '.join(gaps_filled[:5])}.")
    if excluded:
        recs.append(f"Excluded {len(excluded)} field(s) from generation per review: {', '.join(excluded[:5])}.")

    summary = (f"{len(final_dataset)} rows ({input_n} original + {len(new_rows)} generated) "
               f"across {len(out_columns)} columns; source mix {source_mix}.")
    if llm is not None:
        try:
            narrated = llm(f"Write one concise sentence summarising a generated test dataset: "
                           f"{len(final_dataset)} rows ({input_n} original + {len(new_rows)} new), "
                           f"{len(out_columns)} columns, source mix {source_mix}, "
                           f"{len(gaps_filled)} gap-filling fields. No preamble.").strip()
            if narrated:
                summary = narrated
        except Exception:
            pass

    report = {
        "summary": summary,
        "row_count": len(final_dataset),
        "input_row_count": input_n,
        "generated_row_count": len(new_rows),
        "columns": out_columns,
        "source_mix_pct": source_mix,
        "gaps_filled_fields": gaps_filled,
        "fields_excluded": excluded,
        "coverage_gaps_total": len(state.get("coverage_gaps", [])),
        "recommendations": recs,
    }
    mode = "LLM-coherent" if llm is not None else "deterministic"
    print(f"NODE_EXIT synthesise: {len(final_dataset)} rows "
          f"({input_n} original + {len(new_rows)} generated, {mode}), {len(out_columns)} columns")
    return {"final_dataset": final_dataset, "report": report}
