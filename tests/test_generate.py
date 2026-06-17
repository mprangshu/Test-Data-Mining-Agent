"""Unit tests for the `generate` node (deterministic path). Run: pytest -q tests/test_generate.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.generate import generate                       # noqa: E402
from test_data_mining.state import (                                        # noqa: E402
    CoverageGap, ExistingRecord, ParsedField, SeedValue, initial_state,
)


def _field(name, category, constraints):
    return ParsedField(name=name, category=category, constraints=constraints,
                       source_test_ids=[], scenario_types=["valid", "boundary", "negative", "edge"])


def _state():
    st = initial_state("x")
    st["parsed_fields"] = [
        _field("email", "Identity", ["required", "email_format"]),
        _field("order_total", "Financial", ["required", ">=0"]),
        _field("currency", "Reference", ["required", "ISO-4217"]),
    ]
    st["seed_values"] = [SeedValue("email", ["user0001@example.com", "user0002@example.com"])]
    st["coverage_gaps"] = [
        CoverageGap("email", "negative", "x"),
        CoverageGap("order_total", "boundary", "x"),
    ]
    st["existing_data"] = [ExistingRecord("order_flow", "order_flow_v1", ["valid"],
                                          {"currency": ["USD", "GBP"]})]
    return st


def test_candidate_sets_shape_and_grounding():
    out = generate(_state())   # llm=None → deterministic
    by_field = {fc.field_name: fc for fc in out["candidate_sets"]}

    # email: gen_A seeded + valid; gen_B targets the negative gap; gap_flagged
    email = by_field["email"]
    set_ids = {s.set_id for s in email.sets}
    assert {"gen_A", "gen_B"} <= set_ids
    assert email.gap_flagged is True
    gen_a = next(s for s in email.sets if s.set_id == "gen_A")
    assert "user0001@example.com" in gen_a.values            # seeded
    assert all("@" in str(v) for v in gen_a.values)          # constraint-valid (email_format)
    gen_b = next(s for s in email.sets if s.set_id == "gen_B")
    assert "negative" in gen_b.scenario_coverage

    # order_total: gen_B targets the boundary gap (includes 0.00 / extreme)
    ot_b = next(s for s in by_field["order_total"].sets if s.set_id == "gen_B")
    assert "boundary" in ot_b.scenario_coverage
    assert any(str(v) in {"0.00", "0.01", "9999999.99"} for v in ot_b.values)

    # currency: existing set passed through from MongoDB; gen_A values are valid ISO-4217
    cur = by_field["currency"]
    assert any(s.set_id == "existing" and s.values == ["USD", "GBP"] for s in cur.sets)
    gen_a_cur = next(s for s in cur.sets if s.set_id == "gen_A")
    assert all(len(str(v)) == 3 and str(v).isupper() for v in gen_a_cur.values)


def test_field_without_gap_is_not_flagged():
    st = initial_state("x")
    st["parsed_fields"] = [_field("email", "Identity", ["required", "email_format"])]
    st["coverage_gaps"] = []
    fc = generate(st)["candidate_sets"][0]
    assert fc.gap_flagged is False
    assert {"gen_A", "gen_B"} <= {s.set_id for s in fc.sets}   # still offers sets to choose from
