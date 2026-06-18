"""
Phase 9 acceptance tests — additive, always-larger, schema-agnostic output (docs/IMPROVEMENT.md §8).

These pin the headline guarantees that earlier broke (50 rows in → 6 placeholder rows out):
  * output strictly larger than input (hard rule),
  * every original row preserved unchanged (additive, never subtractive),
  * output columns == uploaded columns exactly (schema-agnostic, any names/count/order),
  * honest scenario tags on new rows (never `generated_NNN`), only when those columns exist,
  * zero `sample_value_*` / `generated_\\d+` placeholders,
  * expands with and without result files (Mode A / Mode B).

Run: pytest -q tests/test_additive_output.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from test_data_mining.nodes.parse import parse              # noqa: E402
from test_data_mining.nodes.generate import generate        # noqa: E402
from test_data_mining.nodes.coverage_gap import coverage_gap  # noqa: E402
from test_data_mining.nodes.review import auto_selections    # noqa: E402
from test_data_mining.nodes.synthesise import synthesise     # noqa: E402
from test_data_mining.state import ReviewSelection, initial_state  # noqa: E402

_PLACEHOLDER = re.compile(r"(sample_value_\d+|generated_\d+)", re.IGNORECASE)

# A deliberately NON-order-flow schema (subscription) with custom column names + order.
_SUBS_CSV = (
    "subscription_id,customer_name,email,plan_type,amount,scenario_tag,data_category\n"
    "SUB-1,Alice,alice@example.com,premium,29.99,new_sub,valid\n"
    "SUB-2,Bob,bob@example.com,basic,9.99,trial,valid\n"
    "SUB-3,,not-an-email,premium,29.99,bad_email,negative\n"
    "SUB-4,Dana,dana@example.com,enterprise,299.00,big_plan,valid\n"
)

# A schema with NO scenario_tag / data_category columns at all (must never be invented).
_PLAIN_CSV = (
    "widget_id,widget_name,price\n"
    "W-1,Sprocket,4.50\n"
    "W-2,Gear,9.00\n"
    "W-3,Cog,1.25\n"
)


def _run(tmp_path, csv_text: str, with_results: bool, selections=None):
    """Drive parse → coverage_gap → generate → synthesise (offline, no LLM)."""
    tc = tmp_path / "test_cases"
    tc.mkdir(parents=True, exist_ok=True)
    (tc / "cases.csv").write_text(csv_text, encoding="utf-8")
    st = initial_state(str(tmp_path))
    st.update(parse(st))
    # Mode A vs Mode B: with_results flips whether any scenario was "exercised".
    if with_results:
        from test_data_mining.state import ResultSignal
        st["result_signals"] = [ResultSignal("t", "new_sub", "valid", "passed", st["input_columns"])]
    st.update(coverage_gap(st))
    st.update(generate(st))
    cands = st["candidate_sets"]
    if selections is None:
        sels = auto_selections(cands)
        st["review_selections"] = [ReviewSelection(s["field_name"], s["include"], s["chosen_set_id"])
                                   for s in sels]
    else:
        st["review_selections"] = selections
    st.update(synthesise(st))   # llm=None → deterministic
    return st


def test_output_strictly_larger_and_additive(tmp_path):
    st = _run(tmp_path, _SUBS_CSV, with_results=True)
    out, originals = st["final_dataset"], st["input_rows"]
    assert len(out) > st["input_row_count"]                 # hard rule: always larger
    assert st["input_row_count"] == 4
    # additive: every original row appears unchanged, in order, at the front
    assert out[:len(originals)] == originals


def test_output_columns_match_upload_exactly(tmp_path):
    st = _run(tmp_path, _SUBS_CSV, with_results=True)
    expected = ["subscription_id", "customer_name", "email", "plan_type",
                "amount", "scenario_tag", "data_category"]
    assert st["input_columns"] == expected
    for row in st["final_dataset"]:
        assert list(row.keys()) == expected                 # exact names AND order, every row


def test_no_placeholder_values_anywhere(tmp_path):
    st = _run(tmp_path, _SUBS_CSV, with_results=False)
    for row in st["final_dataset"]:
        for col, val in row.items():
            # scenario_tag legitimately carries "valid_001" etc. — exclude it from the scan
            if col == "scenario_tag":
                continue
            assert not _PLACEHOLDER.search(str(val)), f"placeholder leaked in {col}: {val!r}"


def test_honest_scenario_tags_on_new_rows(tmp_path):
    st = _run(tmp_path, _SUBS_CSV, with_results=False)
    new_rows = st["final_dataset"][st["input_row_count"]:]
    assert new_rows
    for row in new_rows:
        assert row["data_category"] in {"valid", "boundary", "negative", "edge"}
        assert not row["scenario_tag"].startswith("generated_")
        # tag prefix agrees with the category (honest tagging)
        assert row["scenario_tag"].rsplit("_", 1)[0] == row["data_category"]


def test_schema_without_scenario_columns_is_not_invented(tmp_path):
    st = _run(tmp_path, _PLAIN_CSV, with_results=False)
    assert st["input_columns"] == ["widget_id", "widget_name", "price"]
    for row in st["final_dataset"]:
        assert "scenario_tag" not in row                    # never add a column the input lacked
        assert "data_category" not in row
        assert list(row.keys()) == ["widget_id", "widget_name", "price"]
    assert len(st["final_dataset"]) > st["input_row_count"]


def test_expands_in_both_modes(tmp_path):
    a = _run(tmp_path / "a", _SUBS_CSV, with_results=True)
    b = _run(tmp_path / "b", _SUBS_CSV, with_results=False)
    assert len(a["final_dataset"]) > a["input_row_count"]
    assert len(b["final_dataset"]) > b["input_row_count"]


def test_excluded_field_keeps_column_but_not_dropped(tmp_path):
    """Excluding a field from generation must NOT drop its column — originals keep it; the schema
    is preserved (new rows reuse a real value for that column)."""
    # Build selections that exclude 'plan_type'
    tc = tmp_path / "test_cases"
    tc.mkdir(parents=True)
    (tc / "cases.csv").write_text(_SUBS_CSV, encoding="utf-8")
    st = initial_state(str(tmp_path))
    st.update(parse(st))
    st.update(coverage_gap(st))
    st.update(generate(st))
    sels = []
    for s in auto_selections(st["candidate_sets"]):
        include = s["field_name"] != "plan_type"
        sels.append(ReviewSelection(s["field_name"], include, s["chosen_set_id"] if include else None))
    st["review_selections"] = sels
    st.update(synthesise(st))
    for row in st["final_dataset"]:
        assert "plan_type" in row                           # column survives exclusion
    assert "plan_type" in st["report"]["fields_excluded"]
