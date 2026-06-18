"""
Adversarial / graceful-degradation tests (pivot §11 invariant #4): malformed inputs and
unreachable/empty stores must degrade to empty results + gap notes, never crash.

Run: pytest -q tests/test_adversarial.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.parse import parse                  # noqa: E402
from test_data_mining.nodes.load_results import load_results    # noqa: E402
from test_data_mining.nodes.mongo_lookup import mongo_lookup    # noqa: E402
from test_data_mining.nodes.vector_search import vector_search  # noqa: E402
from test_data_mining.state import ParsedField, initial_state   # noqa: E402


def _pf(name="email"):
    st = initial_state("x")
    st["parsed_fields"] = [ParsedField(name, "Identity", ["required"], [], ["valid"])]
    return st


def test_parse_malformed_json_is_flagged(tmp_path):
    (tmp_path / "test_cases").mkdir()
    (tmp_path / "test_cases" / "bad.json").write_text("{ not json ", encoding="utf-8")
    out = parse(initial_state(str(tmp_path)))
    assert out["parsed_fields"] == []
    assert any("bad.json" in g for g in out["gaps"])


def test_load_results_corrupt_xml_skipped(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "bad.xml").write_text("<testsuite><testcase>unclosed", encoding="utf-8")
    out = load_results(initial_state(str(tmp_path)))
    assert out["result_signals"] == []
    assert any("bad.xml" in g for g in out["gaps"])


def test_load_results_no_dir_unseeded(tmp_path):
    out = load_results(initial_state(str(tmp_path)))   # no results/ dir
    assert out["seed_values"] == []
    assert any("unseeded" in g for g in out["gaps"])


def test_mongo_unreachable_degrades(monkeypatch):
    # A bogus URI → connection failure → empty + gap, no crash.
    monkeypatch.setenv("MONGODB_URI", "mongodb://127.0.0.1:1/doesnotexist")
    out = mongo_lookup(_pf())
    assert out["existing_data"] == []
    assert any("unavailable" in g or "LLM-only" in g for g in out["gaps"])


def test_chroma_missing_degrades(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "nope"))
    monkeypatch.setenv("CHROMA_COLLECTION", "tdm_cases")
    out = vector_search(_pf())
    assert out["retrieved_data"] == []
    assert any("ChromaDB unavailable" in g for g in out["gaps"])
