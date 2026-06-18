"""
Phase 3 acceptance — per-row provenance + clean CSV (CONTEXT-v3 §3).

`output_rows` carry source (input/generated/fetched/gathered) + row_uid for the UI; `final_dataset`
(the CSV content) is clean — fields only, no `source` key, original columns exactly.

Run: pytest -q tests/test_provenance.py
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
from test_data_mining.state import (                           # noqa: E402
    ExistingRecord, RetrievedRecord, ReviewSelection, initial_state,
)

_CSV = (
    "order_id,country,currency,scenario_tag,data_category\n"
    "ORD-1,US,USD,a,valid\n"
    "ORD-2,GB,GBP,b,valid\n"
)
_COLUMNS = ["order_id", "country", "currency", "scenario_tag", "data_category"]


def _base_state(tmp_path):
    tc = tmp_path / "test_cases"
    tc.mkdir(parents=True, exist_ok=True)
    (tc / "cases.csv").write_text(_CSV, encoding="utf-8")
    st = initial_state(str(tmp_path))
    st.update(parse(st))
    st.update(coverage_gap(st))
    st.update(generate(st))
    st["review_selections"] = [ReviewSelection(s["field_name"], s["include"], s["chosen_set_id"])
                               for s in auto_selections(st["candidate_sets"])]
    return st


def test_output_rows_carry_source_and_uid(tmp_path):
    st = _base_state(tmp_path)
    st.update(synthesise(st))
    rows = st["output_rows"]
    assert rows
    assert all(r.source in {"input", "generated", "fetched", "gathered"} for r in rows)
    assert len({r.row_uid for r in rows}) == len(rows)             # uids unique
    # originals tagged input, in front, verbatim
    inputs = [r for r in rows if r.source == "input"]
    assert len(inputs) == st["input_row_count"]
    assert inputs[0].fields == st["input_rows"][0]


def test_final_dataset_is_clean_no_provenance(tmp_path):
    st = _base_state(tmp_path)
    st.update(synthesise(st))
    for row in st["final_dataset"]:
        assert "source" not in row and "row_uid" not in row
        assert list(row.keys()) == _COLUMNS                       # original columns only, in order
    # the clean CSV rows are exactly the output_rows' fields
    assert st["final_dataset"] == [r.fields for r in st["output_rows"]]


def test_fetched_and_gathered_rows_tagged(tmp_path):
    """With row-aligned store data, fetched (Mongo) + gathered (Chroma) rows appear, tagged, with
    fresh unique ids (never colliding with originals)."""
    st = _base_state(tmp_path)
    st["existing_data"] = [ExistingRecord(
        test_case_id="orders", label="orders_v1", tags=["order"],
        fields={"country": ["FR"], "currency": ["EUR"]},
        rows=[{"order_id": "ORD-1", "country": "FR", "currency": "EUR"}])]   # note: id clashes with input
    st["retrieved_data"] = [RetrievedRecord(
        test_case_id="orders", similarity_score=0.9,
        fields={"country": ["JP"]},
        rows=[{"order_id": "ORD-2", "country": "JP", "currency": "JPY"}])]
    st.update(synthesise(st))

    by_src = {}
    for r in st["output_rows"]:
        by_src.setdefault(r.source, []).append(r)
    assert by_src.get("fetched") and by_src.get("gathered")
    # fetched/gathered values carried through; ids re-minted so all PKs stay unique
    assert by_src["fetched"][0].fields["country"] == "FR"
    assert by_src["gathered"][0].fields["currency"] == "JPY"
    all_ids = [r.fields["order_id"] for r in st["output_rows"]]
    assert len(all_ids) == len(set(all_ids)), "primary keys must be unique across all sources"
