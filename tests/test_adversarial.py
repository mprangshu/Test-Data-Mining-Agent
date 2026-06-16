"""
Adversarial / edge-case tests (spec §4, Adversarial layer).

Corrupt and empty files, single-run history, and mixed formats must degrade gracefully —
partial results with flagged gaps, never a crash.

Run:  pytest -q tests/test_adversarial.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from test_data_mining.nodes.ingest import ingest                     # noqa: E402
from test_data_mining.nodes.flaky_detect import flaky_detect         # noqa: E402
from test_data_mining.state import initial_state                     # noqa: E402


def _good_junit() -> str:
    return ('<testsuite name="s"><testcase classname="pkg.T" name="a" time="0.1"/>'
            '<testcase classname="pkg.T" name="b" time="0.1"/></testsuite>')


def _pw(cases: list[tuple[str, str]]) -> str:
    specs = [{
        "title": t,
        "tests": [{"results": [{
            "status": s, "duration": 100,
            "error": None if s == "passed" else {"message": "boom", "stack": "st"},
        }]}],
    } for t, s in cases]
    return json.dumps({"config": {"metadata": {}}, "suites": [{"title": "pw", "specs": specs}]})


def test_corrupt_xml_is_skipped_not_fatal(tmp_path):
    run = tmp_path / "run_00"
    run.mkdir()
    (run / "good.xml").write_text(_good_junit(), encoding="utf-8")
    (run / "bad.xml").write_text("<testsuite><testcase>unclosed", encoding="utf-8")

    state = initial_state(str(tmp_path))
    out = ingest(state)
    assert len(out["raw_results"]) == 2                       # good file still parsed
    assert any("bad.xml" in g for g in out["gaps"])           # corrupt one flagged


def test_malformed_json_is_skipped(tmp_path):
    run = tmp_path / "run_00"
    run.mkdir()
    (run / "results.json").write_text("{ not valid json ", encoding="utf-8")

    out = ingest(initial_state(str(tmp_path)))
    assert out["raw_results"] == []
    assert any("results.json" in g for g in out["gaps"])


def test_mixed_formats_in_one_run(tmp_path):
    run = tmp_path / "run_00"
    run.mkdir()
    (run / "results.xml").write_text(_good_junit(), encoding="utf-8")
    (run / "results.json").write_text(_pw([("pw_spec", "failed")]), encoding="utf-8")

    out = ingest(initial_state(str(tmp_path)))
    formats = {r.source_format for r in out["raw_results"]}
    assert formats == {"junit", "playwright"}
    assert len(out["raw_results"]) == 3                       # 2 junit + 1 playwright


def test_single_run_reports_insufficient_history(tmp_path):
    run = tmp_path / "run_00"
    run.mkdir()
    (run / "results.xml").write_text(_good_junit(), encoding="utf-8")

    state = initial_state(str(tmp_path))
    state.update(ingest(state))
    out = flaky_detect(state)
    assert all(f.verdict == "insufficient_history" for f in out["flaky_findings"])


def test_empty_dir_yields_no_results(tmp_path):
    out = ingest(initial_state(str(tmp_path)))
    assert out["raw_results"] == []
