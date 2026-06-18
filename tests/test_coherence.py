"""
Phase 2 acceptance — coherent, grounded, schema-agnostic generation (IMPROVEMENT-2.md §6).

Offline path (no LLM) — clone-and-perturb. Asserts the six defects are fixed:
  unique ids · valid present · tag matches content · mostly-empty stays empty · correlations
  preserved on valid rows · output ≥ input. Plus a SECOND, totally different schema (loans) to
  prove no subscription/order artifacts and no hardcoded column names.

Run: pytest -q tests/test_coherence.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.parse import parse                 # noqa: E402
from test_data_mining.nodes.coverage_gap import coverage_gap   # noqa: E402
from test_data_mining.nodes.generate import generate           # noqa: E402
from test_data_mining.nodes.review import auto_selections      # noqa: E402
from test_data_mining.nodes.synthesise import synthesise       # noqa: E402
from test_data_mining.state import ReviewSelection, initial_state  # noqa: E402

# country↔currency is 1:1; `plan`/`amount` coupled; `coupon` mostly empty; has scenario columns.
_ORDERS = (
    "order_id,country,currency,plan,amount,coupon,scenario_tag,data_category\n"
    "ORD-001,US,USD,free,0.00,,baseline,valid\n"
    "ORD-002,GB,GBP,premium,29.99,WELCOME,paid_gb,valid\n"
    "ORD-003,US,USD,premium,29.99,,paid_us,valid\n"
    "ORD-004,GB,GBP,free,0.00,,free_gb,valid\n"
    "ORD-005,IN,INR,premium,1999.00,SAVE20,india,valid\n"
    "ORD-006,US,USD,premium,29.99,,paid_us2,valid\n"
)

# A totally different domain — loans. Different columns, different coherence, NO scenario columns.
_LOANS = (
    "loan_id,applicant,principal,term_months,rate_pct,status\n"
    "LN-1000,Alice,10000,36,5.5,approved\n"
    "LN-1001,Bob,25000,60,6.0,approved\n"
    "LN-1002,Cara,5000,12,4.5,pending\n"
    "LN-1003,Dan,40000,72,7.2,approved\n"
    "LN-1004,Eve,15000,24,5.0,rejected\n"
)


def _run(tmp_path, csv_text):
    tc = tmp_path / "test_cases"
    tc.mkdir(parents=True, exist_ok=True)
    (tc / "cases.csv").write_text(csv_text, encoding="utf-8")
    st = initial_state(str(tmp_path))
    st.update(parse(st))
    st.update(coverage_gap(st))
    st.update(generate(st))
    st["review_selections"] = [ReviewSelection(s["field_name"], s["include"], s["chosen_set_id"])
                               for s in auto_selections(st["candidate_sets"])]
    st.update(synthesise(st))      # llm=None → clone-and-perturb
    return st


def _new_rows(st):
    return st["final_dataset"][st["input_row_count"]:]


# ── Defect 5: unique ids, continuing the observed pattern ──
def test_unique_ids_continue_pattern(tmp_path):
    st = _run(tmp_path, _ORDERS)
    ids = [r["order_id"] for r in st["final_dataset"]]
    assert len(ids) == len(set(ids)), "duplicate primary keys in output"
    new_ids = [r["order_id"] for r in _new_rows(st)]
    assert all(i.startswith("ORD-") for i in new_ids)           # pattern continued
    assert all(i not in {"ORD-001", "ORD-002", "ORD-003", "ORD-004", "ORD-005", "ORD-006"}
               for i in new_ids)                                # never reuse an existing id


# ── Defect 4: valid rows present ──
def test_valid_rows_present(tmp_path):
    st = _run(tmp_path, _ORDERS)
    cats = {r["data_category"] for r in _new_rows(st)}
    assert "valid" in cats
    assert cats <= {"valid", "boundary", "negative", "edge"}
    assert st["report"]["scenario_mix"].get("valid", 0) >= 1


# ── Defect 6 + coherence: valid rows respect the country↔currency link ──
def test_valid_rows_are_coherent(tmp_path):
    st = _run(tmp_path, _ORDERS)
    real_pairs = {("US", "USD"), ("GB", "GBP"), ("IN", "INR")}
    for r in _new_rows(st):
        if r["data_category"] == "valid" and r["country"] and r["currency"]:
            assert (r["country"], r["currency"]) in real_pairs, \
                f"incoherent valid row: {r['country']}/{r['currency']}"


# ── Defect 3: mostly-empty optional column stays mostly empty (no bare counters) ──
def test_optional_column_stays_mostly_empty(tmp_path):
    st = _run(tmp_path, _ORDERS)
    new = _new_rows(st)
    filled = sum(1 for r in new if str(r["coupon"]).strip())
    assert filled <= len(new) / 2, "optional column got over-filled"
    for r in new:                                               # never a bare 1,2,3 counter
        assert r["coupon"] in {"", "WELCOME", "SAVE20"} or not r["coupon"].isdigit()


# ── Universality: a second, totally different schema, no artifacts, no hardcoding ──
def test_second_schema_loans(tmp_path):
    st = _run(tmp_path, _LOANS)
    cols = ["loan_id", "applicant", "principal", "term_months", "rate_pct", "status"]
    assert st["input_columns"] == cols
    assert len(st["final_dataset"]) > st["input_row_count"]          # expands
    assert "scenario_tag" not in st["final_dataset"][0]             # never invented
    assert "data_category" not in st["final_dataset"][0]
    for r in st["final_dataset"]:
        assert list(r.keys()) == cols                              # schema preserved exactly
    new_ids = [r["loan_id"] for r in _new_rows(st)]
    assert len(new_ids) == len(set(new_ids))                       # unique
    assert all(i.startswith("LN-") for i in new_ids)               # observed pattern continued
    blob = " ".join(str(v) for r in st["final_dataset"] for v in r.values())
    for artifact in ("plan_type", "currency", "order_id", "sample_value_"):
        assert artifact not in blob                                # zero cross-domain leakage


# ── Still additive + ≥ input ──
def test_additive_and_not_smaller(tmp_path):
    st = _run(tmp_path, _LOANS)
    originals = st["input_rows"]
    assert st["final_dataset"][:len(originals)] == originals        # verbatim, in front
    assert len(st["final_dataset"]) >= st["input_row_count"]
