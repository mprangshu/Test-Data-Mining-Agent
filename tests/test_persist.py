"""
Unit tests for `persist` / `write_dataset` and the save→reuse loop.
Run: pytest -q tests/test_persist.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.persist import write_dataset            # noqa: E402
from test_data_mining.nodes.mongo_lookup import mongo_lookup        # noqa: E402
from test_data_mining.state import ParsedField, initial_state       # noqa: E402

_ROWS = [
    {"email": "a@b.com", "order_total": "10.00", "scenario_tag": "t1", "data_category": "generated"},
    {"email": "c@d.com", "order_total": "0.00", "scenario_tag": "t2", "data_category": "generated"},
]


def test_write_dataset_local_seed_and_chroma(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "mongo"))
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    receipt = write_dataset(_ROWS, "order_flow_v2", ["order", "generated"])
    assert receipt["rows"] == 2
    assert set(receipt["fields"]) == {"email", "order_total"}     # scenario columns excluded
    assert receipt["location"].endswith("order_flow_v2.json")
    assert receipt["chroma_indexed"] is True

    doc = json.loads(Path(receipt["location"]).read_text())
    assert doc["label"] == "order_flow_v2"
    assert doc["fields"]["email"] == ["a@b.com", "c@d.com"]


def test_save_then_mongo_lookup_finds_it(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "mongo"))
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))

    write_dataset(_ROWS, "order_flow_v2", ["order"])              # save

    st = initial_state("x")
    st["parsed_fields"] = [ParsedField("email", "Identity", ["required"], [], ["valid"])]
    out = mongo_lookup(st)                                        # re-run lookup
    labels = {e.label for e in out["existing_data"]}
    assert "order_flow_v2" in labels                             # loop closed
