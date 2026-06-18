"""
Phase 8 — full-graph universality on a SECOND, totally different schema (IoT sensors).

Drives the compiled graph end-to-end (parse → gather → coverage_gap → generate → review → resume →
synthesise) on a sensor schema with NO scenario columns and a different id pattern, then asserts the
whole v3 acceptance matrix: additive & ≥ input, schema preserved exactly, per-row provenance,
clean dataset (no source/row_uid), unique ids continuing the observed pattern, and ZERO
cross-domain (order/subscription) artifacts. Stores are redirected to tmp so repo seeds are untouched.

Run: pytest -q tests/test_universality_e2e.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from test_data_mining.graph import build_graph                  # noqa: E402
from test_data_mining.nodes.review import auto_selections       # noqa: E402
from test_data_mining.state import initial_state                # noqa: E402

_SENSORS = (
    "sensor_id,location,temperature_c,humidity_pct,reading_at,status\n"
    "SEN-001,warehouse_a,21.4,45,2026-02-01T00:00:00Z,ok\n"
    "SEN-002,warehouse_b,19.8,52,2026-02-01T01:00:00Z,ok\n"
    "SEN-003,cold_store,3.2,80,2026-02-01T02:00:00Z,ok\n"
    "SEN-004,warehouse_a,22.0,44,2026-02-01T03:00:00Z,ok\n"
    "SEN-005,cold_store,2.9,82,2026-02-01T04:00:00Z,alert\n"
    "SEN-006,dock,15.6,60,2026-02-01T05:00:00Z,ok\n"
)
_COLUMNS = ["sensor_id", "location", "temperature_c", "humidity_pct", "reading_at", "status"]


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_LOCAL_DIR", str(tmp_path / "mongo"))   # empty → no fetched rows
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))      # missing → no gathered rows


def _inputs(tmp_path):
    (tmp_path / "test_cases").mkdir(parents=True, exist_ok=True)
    (tmp_path / "test_cases" / "sensors.csv").write_text(_SENSORS, encoding="utf-8")
    return str(tmp_path)


def test_full_graph_second_schema(tmp_path):
    from langgraph.types import Command

    g = build_graph()
    cfg = {"configurable": {"thread_id": "u-sensors"}}
    g.invoke(initial_state(_inputs(tmp_path / "in")), config=cfg)
    assert g.get_state(cfg).next == ("review",)                 # paused at the gate

    cands = g.get_state(cfg).values["candidate_sets"]
    g.invoke(Command(resume={"review_selections": auto_selections(cands)}), config=cfg)
    final = g.get_state(cfg).values
    assert g.get_state(cfg).next == ()                          # completed

    fd = final["final_dataset"]
    out = final["output_rows"]
    input_n = final["input_row_count"]

    # additive & ≥ input; schema preserved exactly
    assert input_n == 6
    assert len(fd) > input_n
    assert final["input_columns"] == _COLUMNS
    for row in fd:
        assert list(row.keys()) == _COLUMNS
        assert "scenario_tag" not in row and "data_category" not in row   # never invented
        assert "source" not in row and "row_uid" not in row              # clean dataset

    # per-row provenance present (input + generated; stores empty here)
    sources = {r.source for r in out}
    assert "input" in sources and "generated" in sources
    assert sources <= {"input", "generated", "fetched", "gathered"}
    assert len({r.row_uid for r in out}) == len(out)

    # unique ids continuing the observed pattern; no cross-domain leakage
    ids = [r["sensor_id"] for r in fd]
    assert len(ids) == len(set(ids))
    new_ids = [r["sensor_id"] for r in fd[input_n:]]
    assert all(i.startswith("SEN-") for i in new_ids)
    blob = " ".join(str(v) for r in fd for v in r.values())
    for artifact in ("order_id", "currency", "plan_type", "subscription", "sample_value_", "generated_0"):
        assert artifact not in blob
