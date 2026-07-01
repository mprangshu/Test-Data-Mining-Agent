"""
synthesise.py — Assemble the final dataset (pivot §10, G5). Coherent + grounded (CONTEXT-v3 §2,
IMPROVEMENT-2.md). Schema-agnostic: nothing here references a column name or a domain rule.

  final_dataset = original uploaded rows (VERBATIM)  +  newly generated COHERENT rows

The new rows are generated as **whole records**, not index-zipped columns (that was the source of
the incoherence: mismatched country/currency, free-plan-with-price, duplicate ids, no valid rows):

  * **Primary (LLM):** prompt the model with the exact columns + real example rows (originals) and
    known real values per column (grounded on fetched=MongoDB + gathered=ChromaDB), asking it to
    INFER the data types and inter-column relationships and emit fresh coherent rows per scenario.
  * **Offline fallback:** clone a real row and perturb only what the scenario needs, so coherence
    survives without knowing the domain (IMPROVEMENT-2 §1b). Relationships come from the cloned
    real row, never from hardcoded rules.

Guarantees: originals verbatim; id-like columns get fresh unique ids; mostly-empty columns stay
mostly empty; `valid` is always in the mix; scenario tags match content; output ≥ input (soft
target ≥ input rows — no hard cap, never fail for "too many"). `scenario_tag`/`data_category` are
written only if those columns exist in the upload.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from ..inference import IdMinter, cooccurrence, correlated_pairs, profile_columns
from ..state import AgentState, CandidateSet, FieldCandidates, OutputRow, ReviewSelection

_SCENARIOS = ["valid", "boundary", "negative", "edge"]
_TAG_COL, _CAT_COL = "scenario_tag", "data_category"
_META_COLS = {_TAG_COL, _CAT_COL}
_MIN_NEW = 5                 # soft floor; otherwise aim for ≥ input rows (CONTEXT-v3 §1, relaxed)
_MAX_STORE = 10              # cap reused rows surfaced per source (fetched / gathered)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


# ── chosen-set resolution (HITL selections; auto-resume falls back to widest coverage) ──
def _chosen_set(fc: FieldCandidates, sel: ReviewSelection | None) -> CandidateSet | None:
    if sel and sel.chosen_set_id:
        # If the analyst selected an explicit set, use it, else take widest scenario coverage.
        for s in fc.sets:
            if s.set_id == sel.chosen_set_id:
                return s
    return max(fc.sets, key=lambda s: len(s.scenario_coverage)) if fc.sets else None


def _resolve_chosen(state: AgentState):
    # Return a map of field -> (values, source, coverage) for the chosen candidate set,
    # plus a list of excluded fields where the reviewer opted out or no values exist.
    cands = {fc.field_name: fc for fc in state.get("candidate_sets", [])}
    sels = {s.field_name: s for s in state.get("review_selections", [])}
    chosen: dict[str, tuple[list, str, list[str]]] = {}
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
    return chosen, excluded


# ── observed value pools (originals + analyst picks + fetched + gathered) ──
def _dedupe(vals: list) -> list:
    # Preserve input order while removing duplicate values.
    seen, out = set(), []
    for v in vals:
        k = str(v)
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _observed_pools(columns, input_rows, chosen, existing_data, retrieved_data) -> dict[str, list]:
    """Real values seen per column, from every source — the raw material for perturbation + LLM
    grounding. Analyst picks and stored (fetched/gathered) values bias generation toward reuse."""
    pools: dict[str, list] = {c: [] for c in columns}
    for r in input_rows:
        for c in columns:
            v = r.get(c, "")
            if str(v).strip():
                pools[c].append(v)
    for c, (vals, _s, _cov) in chosen.items():
        if c in pools:
            pools[c].extend(v for v in vals if str(v).strip())
    for rec in list(existing_data) + list(retrieved_data):
        for c, vals in getattr(rec, "fields", {}).items():
            if c in pools:
                pools[c].extend(v for v in vals if str(v).strip())
    return {c: _dedupe(v) for c, v in pools.items()}


def _rows_from_pools(pools, columns) -> list[dict]:
    """Degenerate base when there are NO original rows (e.g. Gherkin-only input): zip pools.
    Best-effort only — coherence needs real rows or the LLM."""
    m = max((len(v) for v in pools.values()), default=0)
    return [{c: (pools[c][i % len(pools[c])] if pools.get(c) else "") for c in columns}
            for i in range(m)]


# ── scenario mix (always includes valid; shifts toward coverage gaps) ──
def _scenario_plan(state: AgentState, n: int) -> list[str]:
    gap_types = {g.scenario_type for g in state.get("coverage_gaps", [])}
    weights = {"valid": 2, "boundary": 1, "negative": 1, "edge": 1}   # valid floor ≥ 2
    for t in gap_types:
        if t in weights:
            weights[t] += 1
    cycle: list[str] = []
    for t in _SCENARIOS:
        cycle += [t] * weights[t]
    return [cycle[i % len(cycle)] for i in range(n)]


# ── offline clone-and-perturb (coherence from the cloned real row) ──
def _fmt_num(val: float, is_int: bool) -> str:
    return str(int(round(val))) if is_int else f"{val:.2f}"


def _perturb(base, stype, data_cols, profiles, pools, minter, corr, idx) -> dict:
    row = {c: base.get(c, "") for c in profiles}                 # clone the whole real row
    for c in profiles:                                            # always mint fresh unique ids
        if minter.is_id(c):
            row[c] = minter.mint(c)

    if stype == "valid":
        # keep the real (coherent) row; refresh datetime columns to other observed values
        for c in data_cols:
            p = profiles[c]
            if p.ctype == "datetime" and pools.get(c):
                row[c] = pools[c][idx % len(pools[c])]
    elif stype == "boundary":
        nums = [c for c in data_cols if profiles[c].ctype == "numeric"]
        for c in nums:
            p = profiles[c]
            row[c] = _fmt_num(p.num_min if idx % 2 == 0 else p.num_max, p.numeric_is_int)
    elif stype == "negative":
        # corrupt exactly ONE field — empty the most-likely-required (highest fill) column.
        # Never empty an id-like/primary-key column: it was just minted unique above, and a null
        # PK collides across negatives + breaks downstream tools (FIXES-seed §2, Option A). Express
        # invalidity in some OTHER field; id-like columns keep their fresh unique id.
        ranked = sorted((c for c in data_cols if profiles[c].fill_rate > 0 and not minter.is_id(c)),
                        key=lambda c: profiles[c].fill_rate, reverse=True)
        if ranked:
            row[ranked[idx % min(len(ranked), 3)]] = ""
    elif stype == "edge":
        cats = [c for c in data_cols if profiles[c].ctype == "categorical" and len(profiles[c].observed) > 1]
        if cats:
            c = cats[idx % len(cats)]
            obs = profiles[c].observed
            cur = str(row.get(c, ""))
            alt = next((v for v in reversed(obs) if str(v) != cur), obs[-1])  # an unusual observed value
            row[c] = alt
            # carry correlated partners so we don't break a learned link (e.g. country↔currency)
            for (a, b), mapping in corr.items():
                if a == c and str(alt) in mapping:
                    row[b] = mapping[str(alt)]
        else:
            nums = [c for c in data_cols if profiles[c].ctype == "numeric"]
            if nums:
                p = profiles[nums[idx % len(nums)]]
                row[nums[idx % len(nums)]] = _fmt_num(p.num_max * 2 or 1, p.numeric_is_int)
    return {c: row.get(c, "") for c in profiles}


# ── LLM whole-row generation (grounded, coherent) ──
def _strip_fences(text: str) -> str:
    return _FENCE.sub("", (text or "").strip())


def _llm_rows(llm, columns, example_rows, pools, stype, n) -> list[dict]:
    # Provide the model with example rows and known real values so outputs stay grounded.
    hint = {c: pools.get(c, [])[:6] for c in columns}
    prompt = (
        "You are generating synthetic test data.\n"
        f"COLUMNS (use exactly these, same names and order): {columns}\n"
        f"REAL EXAMPLE ROWS (infer the data types, formats, and the relationships BETWEEN columns "
        f"from these — do not assume any domain):\n{example_rows}\n"
        f"KNOWN REAL VALUES per column (reuse where appropriate; these come from existing/similar "
        f"stored data): {hint}\n"
        f"Generate {n} rows for the '{stype}' scenario "
        "(valid=internally consistent & realistic; boundary=limit/extreme values; "
        "negative=intentionally invalid in ONE field, the rest coherent; edge=unusual but plausible).\n"
        "Rules: keep each row INTERNALLY CONSISTENT per the relationships you inferred; produce NEW "
        "values (don't copy the examples verbatim); any unique-id column gets a NEW unique value; "
        "keep mostly-empty columns mostly empty. Return ONLY a JSON array of objects, no prose."
    )
    data = json.loads(_strip_fences(llm(prompt)))
    src = data if isinstance(data, list) else [data]
    return [{c: r.get(c, "") for c in columns} for r in src if isinstance(r, dict)]


def _store_rows(records, columns, cap: int) -> list[dict]:
    """Coherent row-aligned records from a store (fetched=Mongo / gathered=Chroma), mapped to the
    output columns (missing → ""), deduped, capped. Empty when the store has no row-aligned data."""
    out, seen = [], set()
    for rec in records:
        for r in (getattr(rec, "rows", []) or []):
            row = {c: r.get(c, "") for c in columns}
            key = tuple(str(row[c]) for c in columns)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= cap:
                return out
    return out


def _build_new_rows(state, columns, base_rows, input_n, profiles, minter, corr, pools, llm):
    """Generate the NEW (source='generated') rows — coherent whole records, ids minted unique."""
    data_cols = [c for c in columns if c not in _META_COLS]
    n_new = max(input_n, _MIN_NEW) if columns else 0
    plan = _scenario_plan(state, n_new)
    has_tag, has_cat = _TAG_COL in columns, _CAT_COL in columns

    llm_by_type: dict[str, list[dict]] = {}
    if llm is not None and base_rows:
        for stype, cnt in Counter(plan).items():
            try:
                llm_by_type[stype] = _llm_rows(llm, columns, base_rows[:5], pools, stype, cnt)
            except Exception:
                llm_by_type[stype] = []
    cursor: Counter = Counter()

    new_rows: list[dict] = []
    for i, stype in enumerate(plan):
        pool = llm_by_type.get(stype, [])
        k = cursor[stype]
        cursor[stype] += 1
        if k < len(pool) and pool[k]:
            row = {c: pool[k].get(c, "") for c in columns}
            for c in columns:                       # never trust LLM id uniqueness
                if minter.is_id(c):
                    row[c] = minter.mint(c)
        elif base_rows:
            row = _perturb(base_rows[i % len(base_rows)], stype, data_cols, profiles, pools, minter, corr, i)
            row = {c: row.get(c, "") for c in columns}
        else:
            row = {c: "" for c in columns}
        if has_tag:
            row[_TAG_COL] = f"{stype}_{i + 1:03d}"
        if has_cat:
            row[_CAT_COL] = stype
        new_rows.append(row)

    return new_rows, plan


def _mint_row_ids(row, columns, minter) -> dict:
    out = dict(row)
    for c in columns:
        if minter.is_id(c):
            out[c] = minter.mint(c)
    return out


def synthesise(state: AgentState, llm=None) -> dict:
    """LangGraph node: emit `output_rows` with provenance + a clean `final_dataset` (fields only).

    output_rows = input (verbatim) + generated (coherent, grounded) + fetched (Mongo rows) +
    gathered (Chroma rows). Schema-agnostic, output ≥ input. `final_dataset` strips provenance
    for the CSV; `source`/`row_uid` ride alongside in `output_rows` for the UI/API only.
    """
    chosen, excluded = _resolve_chosen(state)
    input_rows = list(state.get("input_rows", []))
    input_n = state.get("input_row_count", len(input_rows))
    field_columns = list(chosen.keys())
    columns = list(state.get("input_columns", [])) or field_columns
    rd = state.get("round_index", 0)

    existing = state.get("existing_data", [])
    retrieved = state.get("retrieved_data", [])
    fetched_src = _store_rows(existing, columns, _MAX_STORE)
    gathered_src = _store_rows(retrieved, columns, _MAX_STORE)

    # Grounding corpus = real coherent rows: originals + reused store rows.
    pools = _observed_pools(columns, input_rows, chosen, existing, retrieved)
    base_rows = (input_rows + fetched_src + gathered_src) or _rows_from_pools(pools, columns)
    # Profile column TYPES from the originals (the schema authority) — store rows repeat ids and
    # would skew id/uniqueness detection. Correlations use the fuller coherent corpus.
    profiles = profile_columns(input_rows or base_rows, columns)
    minter = IdMinter(profiles)
    corr = {(a, b): cooccurrence(base_rows, a, b) for a, b in correlated_pairs(base_rows, profiles)}

    new_rows, plan = _build_new_rows(state, columns, base_rows, input_n, profiles, minter, corr, pools, llm)

    # Assemble output rows with provenance. Originals keep their values+ids verbatim (source=input);
    # generated/fetched/gathered get freshly minted ids so primary keys stay unique across the set.
    output_rows: list[OutputRow] = []
    for i, r in enumerate(input_rows):
        output_rows.append(OutputRow(fields={c: r.get(c, "") for c in columns},
                                     source="input", row_uid=f"r{rd}-i{i}"))
    for i, r in enumerate(new_rows):
        output_rows.append(OutputRow(fields=r, source="generated", row_uid=f"r{rd}-g{i}"))
    for i, r in enumerate(fetched_src):
        output_rows.append(OutputRow(fields=_mint_row_ids(r, columns, minter),
                                     source="fetched", row_uid=f"r{rd}-f{i}"))
    for i, r in enumerate(gathered_src):
        output_rows.append(OutputRow(fields=_mint_row_ids(r, columns, minter),
                                     source="gathered", row_uid=f"r{rd}-h{i}"))

    final_dataset = [o.fields for o in output_rows]       # clean rows for CSV (no source/uid)
    assert not columns or len(final_dataset) >= input_n, "REGRESSION: output smaller than input"

    # reporting
    provenance = dict(Counter(o.source for o in output_rows))
    scenario_mix = dict(Counter(plan))
    gaps_filled = [name for name, (_v, _s, cov) in chosen.items()
                   if any(t in ("boundary", "negative", "edge") for t in cov)]
    gen_n, fet_n, gat_n = len(new_rows), len(fetched_src), len(gathered_src)

    recs: list[str] = [
        f"Additive output: {input_n} input row(s) + {gen_n} generated + {fet_n} fetched "
        f"+ {gat_n} gathered = {len(final_dataset)} total.",
        f"Generated rows are coherent whole records ({'LLM-grounded' if llm else 'clone-and-perturb'}), "
        f"grounded on input + fetched + gathered; scenario mix {scenario_mix}.",
    ]
    if fet_n or gat_n:
        recs.append(f"Reused {fet_n} fetched (MongoDB) + {gat_n} gathered (ChromaDB) row(s).")
    if gaps_filled:
        recs.append(f"Filled coverage gaps for {len(gaps_filled)} field(s): {', '.join(gaps_filled[:5])}.")

    summary = (f"{len(final_dataset)} rows ({input_n} input + {gen_n} generated + {fet_n} fetched "
               f"+ {gat_n} gathered) across {len(columns)} columns; scenario mix {scenario_mix}.")
    if llm is not None:
        try:
            narrated = llm(f"Write one concise sentence summarising a test dataset of "
                           f"{len(final_dataset)} rows across {len(columns)} columns "
                           f"(provenance {provenance}). No preamble.").strip()
            if narrated:
                summary = narrated
        except Exception:
            pass

    report = {
        "summary": summary,
        "row_count": len(final_dataset),
        "input_row_count": input_n,
        "generated_row_count": gen_n,
        "columns": columns,
        "provenance": provenance,
        "scenario_mix": scenario_mix,
        "gaps_filled_fields": gaps_filled,
        "fields_excluded": excluded,
        "coverage_gaps_total": len(state.get("coverage_gaps", [])),
        "recommendations": recs,
    }
    mode = "LLM-grounded" if llm is not None else "clone-and-perturb"
    print(f"NODE_EXIT synthesise: {len(final_dataset)} rows "
          f"(provenance {provenance}, {mode}), {len(columns)} columns")
    return {"final_dataset": final_dataset, "output_rows": output_rows, "report": report}
