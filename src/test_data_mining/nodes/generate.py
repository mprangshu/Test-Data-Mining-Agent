"""
generate.py — Produce 2–3 candidate value SETS per field (pivot §10, G4).

Type: LLM (seam) with a deterministic, fully-grounded default.

Per field it builds:
  * ``gen_A`` — valid-leaning values, seeded from real passing values (`seed_values`) when present,
    optionally enriched by Gemini; every value is **constraint-validated** (anti-hallucination).
  * ``gen_B`` — gap-filling values targeting the field's `coverage_gaps` (boundary/negative/edge).
  * ``existing`` / ``retrieved`` — pass-through sets from MongoDB / ChromaDB when available.

The HITL gate later lets the analyst pick ONE set per field. The LLM is optional: with no key (or
on error/quota) generation is fully deterministic, so this runs offline and in tests.
"""
from __future__ import annotations

from ..state import AgentState, CandidateSet, FieldCandidates

_MAX = 6  # values per set

# Deterministic value pools (field-name specific; generic fallback by scenario type).
_VALID = {
    "email": ["buyer.jane@example.com", "a.kumar@example.org", "sam.lee@example.net"],
    "currency": ["USD", "GBP", "EUR", "INR"],
    "country": ["US", "GB", "DE", "IN"],
    "payment_method": ["credit_card", "paypal", "upi", "debit_card"],
    "order_status": ["completed", "pending", "shipped"],
    "item_count": ["1", "2", "3", "5"],
    "order_total": ["19.95", "58.40", "149.99", "512.18"],
    "customer_name": ["Jane Doe", "Aarav Kumar", "Sam Lee"],
    "card_number_masked": ["****-****-****-4242", "****-****-****-1881"],
    "coupon_code": ["WELCOME10", "SAVE20", "FREESHIP"],
    "order_id": ["ORD-200001", "ORD-200002", "ORD-200003"],
    "created_at": ["2026-02-01T09:00:00Z", "2026-02-03T14:30:00Z"],
    "password": ["P@ssw0rd!", "Str0ng#2026", "Tr0ub4dour&3"],
    "username": ["jane.doe", "akumar", "user_42"],
}
_NEGATIVE = {
    "email": ["", "bad@", "a@", "no-at-symbol"],
    "currency": ["XXX", "US", ""],
    "country": ["", "ZZ", "123"],
    "payment_method": ["", "unsupported_method"],
    "order_status": ["", "not_a_status"],
    "item_count": ["-2", "abc"],
    "order_total": ["-15.00", "NaN"],
    "customer_name": [""],
    "card_number_masked": ["1234", "****"],
    "coupon_code": ["EXPIRED5"],
    "created_at": ["not-a-date", "2026-13-40T99:99:99Z"],
    "password": ["", "123"],
    "username": [""],
}
_BOUNDARY = {
    "order_total": ["0.00", "0.01", "9999999.99"],
    "item_count": ["0", "99"],
    "email": ["a@b.co", ("x" * 64) + "@example.com"],
    "currency": ["usd"],
    "customer_name": ["A", "X" * 256],
    "coupon_code": [""],
    "created_at": ["2026-01-01T00:00:00Z", "2026-12-31T23:59:59Z"],
    "password": ["aA1!", "P" * 64],
}
_EDGE = {
    "order_status": ["refunded", "chargeback", "abandoned"],
    "order_total": ["1234567.89"],
    "item_count": ["1000"],
    "currency": ["JPY", "BRL"],
}
_GENERIC = {
    "valid": ["sample_value_1", "sample_value_2", "sample_value_3"],
    "negative": ["", "INVALID", "!!!"],
    "boundary": ["", "X", "X" * 256],
    "edge": ["<edge-case>"],
}
_TABLE = {"valid": _VALID, "negative": _NEGATIVE, "boundary": _BOUNDARY, "edge": _EDGE}


def _dedupe(values: list) -> list:
    seen, out = set(), []
    for v in values:
        key = str(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _pool(field_name: str, stype: str) -> list:
    return list(_TABLE[stype].get(field_name.lower(), _GENERIC[stype]))


def _valid_value(v, constraints: list[str]) -> bool:
    """Anti-hallucination gate for VALID values — every value must satisfy field constraints."""
    s = str(v)
    if "required" in constraints and not s.strip():
        return False
    if "email_format" in constraints and "@" not in s:
        return False
    if "ISO-4217" in constraints and not (len(s) == 3 and s.isalpha() and s.isupper()):
        return False
    if ">=0" in constraints:
        try:
            if float(s) < 0:
                return False
        except ValueError:
            return False
    if "integer" in constraints:
        if not s.lstrip("-").isdigit():
            return False
    return True


def _llm_valid_values(llm, field, examples: list[str]) -> list[str]:
    """Ask Gemini for realistic valid values; keep only those that pass constraints."""
    try:
        prompt = (
            f"Generate {_MAX} realistic, VALID test-data values for a field named '{field.name}' "
            f"(category: {field.category}; constraints: {', '.join(field.constraints) or 'none'}). "
            f"Examples of real values: {examples[:3]}. "
            f"Return ONLY the values as a comma-separated list, no prose."
        )
        text = llm(prompt)
        vals = [v.strip() for v in text.replace("\n", ",").split(",") if v.strip()]
        return [v for v in vals if _valid_value(v, field.constraints)]
    except Exception:
        return []


def _aggregate(records, field_name: str) -> list:
    out = []
    for rec in records:
        out.extend(rec.fields.get(field_name, []))
    return _dedupe(out)


def generate(state: AgentState, llm=None) -> dict:
    """LangGraph node: build candidate value sets per field."""
    fields = state.get("parsed_fields", [])
    seeds = {s.field_name: s.example_values for s in state.get("seed_values", [])}
    existing = state.get("existing_data", [])
    retrieved = state.get("retrieved_data", [])

    gap_by_field: dict[str, list[str]] = {}
    for g in state.get("coverage_gaps", []):
        gap_by_field.setdefault(g.field_name, []).append(g.scenario_type)

    candidate_sets: list[FieldCandidates] = []
    for f in fields:
        sets: list[CandidateSet] = []

        # gen_A — valid (seeded → optionally LLM-enriched → deterministic), constraint-validated
        seeded = [v for v in (seeds.get(f.name) or []) if _valid_value(v, f.constraints)]
        valid_vals = list(seeded)
        if llm is not None:
            valid_vals += _llm_valid_values(llm, f, seeded or _pool(f.name, "valid"))
        if not valid_vals:
            valid_vals = [v for v in _pool(f.name, "valid") if _valid_value(v, f.constraints)] \
                         or _pool(f.name, "valid")
        note_a = "valid-leaning" + (" (seeded from real data)" if seeded else "")
        sets.append(CandidateSet("gen_A", "generated", _dedupe(valid_vals)[:_MAX], ["valid"], note_a))

        # gen_B — gap-filling (targets this field's coverage gaps; else boundary+negative)
        targets = gap_by_field.get(f.name) or ["boundary", "negative"]
        gb_vals, cover = [], []
        for st in ("boundary", "negative", "edge"):
            if st in targets:
                gb_vals += _pool(f.name, st)
                cover.append(st)
        sets.append(CandidateSet("gen_B", "generated", _dedupe(gb_vals)[:_MAX],
                                 cover or ["boundary", "negative"],
                                 "gap-filling: " + ", ".join(cover or ["boundary", "negative"])))

        # existing / retrieved pass-through sets
        ex_vals = _aggregate(existing, f.name)
        if ex_vals:
            sets.append(CandidateSet("existing", "existing", ex_vals[:_MAX], ["valid"], "from MongoDB"))
        rt_vals = _aggregate(retrieved, f.name)
        if rt_vals:
            sets.append(CandidateSet("retrieved", "retrieved", rt_vals[:_MAX], ["valid"], "from ChromaDB"))

        candidate_sets.append(FieldCandidates(
            field_name=f.name, category=f.category, sets=sets,
            gap_flagged=bool(gap_by_field.get(f.name)),
        ))

    n_llm = "LLM-enriched" if llm is not None else "deterministic"
    print(f"NODE_EXIT generate: {len(candidate_sets)} fields, {n_llm} candidate sets")
    return {"candidate_sets": candidate_sets}
