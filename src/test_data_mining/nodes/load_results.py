"""
load_results.py — Parse the SUPPORTING result files (JUnit XML / Playwright JSON).

Type: deterministic. Reads ``<input_path>/results/`` and produces:
  * ``result_signals`` — per scenario: tag, type, outcome, and which fields it exercised.
  * ``seed_values``    — real values seen in **passing** runs (few-shot seeds for generation).

Convention the demo fixtures emit (pivot §9): each test carries its scenario + field values as
metadata — JUnit ``<property name=… value=…>`` children, Playwright ``annotations`` entries.
Reserved keys (``scenario_type``/``scenario_tag``/``data_category``/``test_case_id``) label the
scenario; every other key is a data field. No ``results/`` dir → empty + a gap note (generation
still works, just unseeded). Never crashes.
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from collections import OrderedDict

from ..state import AgentState, ResultSignal, SeedValue

_RESERVED = {"scenario_tag", "scenario_type", "data_category", "test_case_id"}


def _infer_scenario(tag: str) -> str:
    low = (tag or "").lower()
    if any(w in low for w in ("invalid", "missing", "negative", "error", "reject", "declined")):
        return "negative"
    if any(w in low for w in ("boundary", "max", "min", "zero", "limit", "empty", "smallest", "largest")):
        return "boundary"
    if any(w in low for w in ("edge", "extreme", "refund", "chargeback")):
        return "edge"
    return "valid"


def _seed(seeds: "OrderedDict[str, list]", field_vals: dict) -> None:
    for k, v in field_vals.items():
        seeds.setdefault(k, [])
        if v not in seeds[k]:
            seeds[k].append(v)


def _parse_junit(path: str, signals: list, seeds) -> None:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    for suite in suites:
        for case in suite.findall("testcase"):
            name, classname = case.get("name", ""), case.get("classname", "")
            props = {p.get("name"): p.get("value") for p in case.findall("./properties/property")}
            tcid = props.get("test_case_id") or classname or name
            tag = props.get("scenario_tag") or name
            stype = props.get("scenario_type") or props.get("data_category") or _infer_scenario(tag)
            if case.find("failure") is not None:
                outcome = "failed"
            elif case.find("error") is not None:
                outcome = "error"
            elif case.find("skipped") is not None:
                outcome = "skipped"
            else:
                outcome = "passed"
            field_vals = {k: v for k, v in props.items() if k not in _RESERVED}
            signals.append(ResultSignal(tcid, tag, stype, outcome, list(field_vals)))
            if outcome == "passed":
                _seed(seeds, field_vals)


def _parse_playwright(path: str, signals: list, seeds) -> None:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)

    def ann_map(node) -> dict:
        return {a.get("type"): a.get("description") for a in node.get("annotations", []) if a.get("type")}

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            tag = spec.get("title", "")
            base_ann = ann_map(spec)
            for test in spec.get("tests", []):
                res = (test.get("results") or [{}])[-1]
                status = res.get("status", "passed")
                outcome = status if status in ("passed", "failed", "skipped") else "error"
                ann = {**base_ann, **ann_map(test)}
                tcid = ann.get("test_case_id") or tag
                stype = ann.get("scenario_type") or ann.get("data_category") or _infer_scenario(tag)
                field_vals = {k: v for k, v in ann.items() if k not in _RESERVED}
                signals.append(ResultSignal(tcid, tag, stype, outcome, list(field_vals)))
                if outcome == "passed":
                    _seed(seeds, field_vals)
        for child in suite.get("suites", []):
            walk(child)

    for s in doc.get("suites", []):
        walk(s)


def load_results(state: AgentState) -> dict:
    """LangGraph node: parse supporting results → result_signals + seed_values."""
    base = state["input_path"]
    rdir = os.path.join(base, "results")
    if not os.path.isdir(rdir):
        return {"result_signals": [], "seed_values": [],
                "gaps": ["load_results: no results/ dir — generation will be unseeded"]}

    signals: list[ResultSignal] = []
    seeds: "OrderedDict[str, list]" = OrderedDict()
    gaps: list[str] = []
    found = False
    for dirpath, _dirs, files in os.walk(rdir):
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            fp = os.path.join(dirpath, fn)
            try:
                if ext == ".xml":
                    _parse_junit(fp, signals, seeds)
                    found = True
                elif ext == ".json":
                    _parse_playwright(fp, signals, seeds)
                    found = True
            except Exception as exc:  # never crash — flag and continue
                gaps.append(f"load_results: skipped {fn} ({type(exc).__name__})")

    seed_values = [SeedValue(field_name=k, example_values=v) for k, v in seeds.items()]
    if not found:
        gaps.append("load_results: no result files found — generation will be unseeded")

    print(f"NODE_EXIT load_results: {len(signals)} signals, {len(seed_values)} seeded fields")
    return {"result_signals": signals, "seed_values": seed_values, "gaps": gaps}
