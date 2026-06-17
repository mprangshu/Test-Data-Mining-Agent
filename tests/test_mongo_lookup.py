"""Unit tests for the `mongo_lookup` node (local JSON seed path). Run: pytest -q tests/test_mongo_lookup.py"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.mongo_lookup import mongo_lookup     # noqa: E402
from test_data_mining.state import ParsedField, initial_state    # noqa: E402


def _state(field_names):
    st = initial_state("x")
    st["parsed_fields"] = [
        ParsedField(name=n, category="General", constraints=["required"],
                    source_test_ids=[], scenario_types=["valid"])
        for n in field_names
    ]
    return st


def _seed(dirp, label, fields, tags=None, tcid="order_flow"):
    (dirp / f"{label}.json").write_text(json.dumps({
        "test_case_id": tcid, "label": label, "tags": tags or [], "fields": fields,
    }), encoding="utf-8")


def test_returns_dataset_on_field_overlap(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path))
    _seed(tmp_path, "order_flow_v1", {"email": ["a@b.com"], "order_total": ["10.00"]})
    _seed(tmp_path, "unrelated", {"sku": ["X1"]})

    out = mongo_lookup(_state(["email", "currency"]))
    labels = {e.label for e in out["existing_data"]}
    assert labels == {"order_flow_v1"}                 # matched on `email`, unrelated excluded
    rec = out["existing_data"][0]
    assert rec.fields["email"] == ["a@b.com"]


def test_empty_seed_dir_degrades(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path))   # empty dir
    out = mongo_lookup(_state(["email"]))
    assert out["existing_data"] == []
    assert any("empty" in g or "LLM-only" in g for g in out["gaps"])


def test_no_store_configured_degrades(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "missing"))
    out = mongo_lookup(_state(["email"]))
    assert out["existing_data"] == []
    assert any("LLM-only" in g for g in out["gaps"])
