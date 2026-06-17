"""
Unit tests for the `load_results` node (supporting results → signals + seeds).
Run: pytest -q tests/test_load_results.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.load_results import load_results   # noqa: E402
from test_data_mining.state import initial_state               # noqa: E402


def _results(tmp_path):
    d = tmp_path / "results"
    d.mkdir()
    return d


def test_junit_signals_and_seeds_from_passing(tmp_path):
    (_results(tmp_path) / "junit.xml").write_text(
        '<testsuite name="order_flow">'
        '  <testcase classname="order_flow" name="typical_order">'
        '    <properties>'
        '      <property name="scenario_type" value="valid"/>'
        '      <property name="email" value="user@example.com"/>'
        '      <property name="currency" value="USD"/>'
        '    </properties>'
        '  </testcase>'
        '  <testcase classname="order_flow" name="missing_email">'
        '    <properties>'
        '      <property name="scenario_type" value="negative"/>'
        '      <property name="email" value=""/>'
        '    </properties>'
        '    <failure message="missing email">boom</failure>'
        '  </testcase>'
        '</testsuite>',
        encoding="utf-8",
    )
    out = load_results(initial_state(str(tmp_path)))
    signals = {s.scenario_tag: s for s in out["result_signals"]}
    assert signals["typical_order"].outcome == "passed"
    assert signals["typical_order"].scenario_type == "valid"
    assert set(signals["typical_order"].fields_exercised) == {"email", "currency"}
    assert signals["missing_email"].outcome == "failed"

    seeds = {s.field_name: s.example_values for s in out["seed_values"]}
    # only PASSING values seed
    assert seeds["email"] == ["user@example.com"]
    assert seeds["currency"] == ["USD"]


def test_playwright_annotations(tmp_path):
    doc = {
        "suites": [{
            "specs": [{
                "title": "typical_order",
                "annotations": [
                    {"type": "scenario_type", "description": "valid"},
                    {"type": "country", "description": "US"},
                ],
                "tests": [{"results": [{"status": "passed"}]}],
            }],
        }],
    }
    (_results(tmp_path) / "pw.json").write_text(json.dumps(doc), encoding="utf-8")
    out = load_results(initial_state(str(tmp_path)))
    sig = out["result_signals"][0]
    assert sig.outcome == "passed" and sig.scenario_type == "valid"
    assert "country" in sig.fields_exercised
    seeds = {s.field_name: s.example_values for s in out["seed_values"]}
    assert seeds["country"] == ["US"]


def test_no_results_dir_degrades(tmp_path):
    out = load_results(initial_state(str(tmp_path)))
    assert out["result_signals"] == [] and out["seed_values"] == []
    assert any("no results" in g for g in out["gaps"])
