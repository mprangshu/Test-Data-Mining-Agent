"""
Unit tests for the `parse` node (primary inputs → parsed_fields). Run: pytest -q tests/test_parse.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.parse import parse              # noqa: E402
from test_data_mining.state import initial_state            # noqa: E402


def _tc(tmp_path):
    d = tmp_path / "test_cases"
    d.mkdir()
    return d


def test_parse_csv_headers_become_fields(tmp_path):
    (_tc(tmp_path) / "order_flow.csv").write_text(
        "order_id,email,currency,scenario_tag,data_category\n"
        "ORD-1,a@b.com,USD,typical_order,valid\n"
        "ORD-2,,USD,missing_email,negative\n",
        encoding="utf-8",
    )
    out = parse(initial_state(str(tmp_path)))
    fields = {f.name: f for f in out["parsed_fields"]}
    # scenario/tag columns excluded; data columns kept
    assert set(fields) == {"order_id", "email", "currency"}
    assert fields["email"].category == "Identity"
    assert "email_format" in fields["email"].constraints
    assert fields["currency"].category == "Reference"
    # scenario types collected from data_category column
    assert set(fields["email"].scenario_types) == {"valid", "negative"}


def test_parse_json_list_of_objects(tmp_path):
    (_tc(tmp_path) / "cases.json").write_text(
        json.dumps([{"email": "a@b.com", "order_total": 10, "data_category": "valid"}]),
        encoding="utf-8",
    )
    out = parse(initial_state(str(tmp_path)))
    names = {f.name for f in out["parsed_fields"]}
    assert names == {"email", "order_total"}


def test_parse_gherkin_txt_placeholders(tmp_path):
    (_tc(tmp_path) / "login.txt").write_text(
        "Feature: Login\n"
        "Scenario: invalid password is rejected\n"
        "  Given username <username> and password <password>\n"
        "  When the password is invalid\n"
        "  Then login fails\n",
        encoding="utf-8",
    )
    out = parse(initial_state(str(tmp_path)))
    fields = {f.name: f for f in out["parsed_fields"]}
    assert "username" in fields and "password" in fields
    assert "negative" in fields["username"].scenario_types


def test_parse_malformed_is_flagged_not_fatal(tmp_path):
    (_tc(tmp_path) / "bad.json").write_text("{ not json ", encoding="utf-8")
    out = parse(initial_state(str(tmp_path)))
    assert out["parsed_fields"] == []
    assert any("bad.json" in g for g in out["gaps"])


def test_parse_missing_dir_degrades(tmp_path):
    out = parse(initial_state(str(tmp_path / "nope")))
    assert out["parsed_fields"] == []
    assert any("not found" in g for g in out["gaps"])
