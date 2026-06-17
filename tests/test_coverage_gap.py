"""Unit tests for the `coverage_gap` node. Run: pytest -q tests/test_coverage_gap.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.coverage_gap import coverage_gap          # noqa: E402
from test_data_mining.state import ParsedField, ResultSignal, initial_state  # noqa: E402


def _field(name):
    return ParsedField(name=name, category="General", constraints=[],
                       source_test_ids=[], scenario_types=["valid", "boundary", "negative", "edge"])


def test_gaps_are_unexercised_combinations():
    st = initial_state("x")
    st["parsed_fields"] = [_field("email"), _field("order_total")]
    # Results exercised valid + negative for both fields (negative ran, even if it failed).
    st["result_signals"] = [
        ResultSignal("tc1", "typical", "valid", "passed", ["email", "order_total"]),
        ResultSignal("tc2", "missing", "negative", "failed", ["email", "order_total"]),
    ]
    gaps = {(g.field_name, g.scenario_type) for g in coverage_gap(st)["coverage_gaps"]}
    # boundary + edge never exercised → gaps; valid + negative covered
    assert gaps == {("email", "boundary"), ("email", "edge"),
                    ("order_total", "boundary"), ("order_total", "edge")}


def test_no_signals_means_everything_is_a_gap():
    st = initial_state("x")
    st["parsed_fields"] = [_field("email")]
    st["result_signals"] = []
    types = {g.scenario_type for g in coverage_gap(st)["coverage_gaps"]}
    assert types == {"valid", "boundary", "negative", "edge"}
