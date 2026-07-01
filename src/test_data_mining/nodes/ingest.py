"""
ingest.py — Load configured sources and normalise to a common TestResult schema.

Type: deterministic. This is a WORKING reference implementation for the two MVP
formats (JUnit/TestNG XML, Playwright JSON). It walks ``state["input_path"]`` for
``run_*`` directories, parses every results file, and emits normalised TestResult
records tagged with their run_id.

Graceful degradation: a malformed file is recorded in ``gaps`` and skipped — never
raises. (Spec §1.4.)
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ..state import AgentState, TestResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_junit(path: str, run_id: str) -> list[TestResult]:
    """Parse a JUnit/TestNG XML file into TestResult records."""
    # Returns list of TestResult objects keyed by run_id, outcome, and source_format.
    results: list[TestResult] = []
    tree = ET.parse(path)
    root = tree.getroot()
    # Accept either a <testsuite> root or a <testsuites> wrapper.
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")
    for suite in suites:
        suite_name = suite.get("name", "unknown")
        ts = suite.get("timestamp", _now())
        for case in suite.findall("testcase"):
            classname = case.get("classname", "")
            name = case.get("name", "")
            test_id = f"{classname}#{name}" if classname else name
            duration = float(case.get("time", "0") or 0)

            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if failure is not None:
                outcome, node = "failed", failure
            elif error is not None:
                outcome, node = "error", error
            elif skipped is not None:
                outcome, node = "skipped", skipped
            else:
                outcome, node = "passed", None

            results.append(TestResult(
                test_id=test_id,
                suite=suite_name,
                outcome=outcome,                       # type: ignore[arg-type]
                duration_sec=duration,
                run_id=run_id,
                commit_sha="",                         # filled from manifest if available
                timestamp=ts,
                message=(node.get("message") if node is not None else None),
                stack_trace=((node.text or "").strip() if node is not None else None),
                source_format="junit",
            ))
    return results


def parse_playwright(path: str, run_id: str) -> list[TestResult]:
    """Parse a Playwright JSON reporter file into TestResult records."""
    # Returns list of TestResult objects keyed by run_id, outcome, and source_format.
    results: list[TestResult] = []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    ts = doc.get("config", {}).get("metadata", {}).get("timestamp", _now())

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            test_id = spec.get("title", "")
            for test in spec.get("tests", []):
                res = (test.get("results") or [{}])[-1]
                status = res.get("status", "passed")
                outcome = status if status in ("passed", "failed", "skipped") else "error"
                err = res.get("error") or {}
                results.append(TestResult(
                    test_id=test_id,
                    suite=suite.get("title", "playwright"),
                    outcome=outcome,                   # type: ignore[arg-type]
                    duration_sec=float(res.get("duration", 0)) / 1000.0,
                    run_id=run_id,
                    commit_sha="",
                    timestamp=ts,
                    message=err.get("message"),
                    stack_trace=err.get("stack"),
                    source_format="playwright",
                ))
        for child in suite.get("suites", []):
            walk(child)

    for suite in doc.get("suites", []):
        walk(suite)
    return results


def ingest(state: AgentState) -> dict:
    """LangGraph node: discover run_* dirs, parse all sources, normalise."""
    # This node walks `input_path`, reads every XML/JSON results file, and returns normalized TestResult records.
    input_path = state["input_path"]
    results: list[TestResult] = []
    gaps: list[str] = []

    # Pull the shared commit_sha from the manifest if present (set by the generator).
    commit_sha = ""
    manifest_path = os.path.join(os.path.dirname(input_path.rstrip("/")), "golden", "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                commit_sha = json.load(f).get("commit_sha", "")
        except (OSError, json.JSONDecodeError):
            pass

    if not os.path.isdir(input_path):
        return {"raw_results": [], "gaps": [f"input_path not found: {input_path}"]}

    run_dirs = sorted(d for d in os.listdir(input_path)
                      if os.path.isdir(os.path.join(input_path, d)))
    for run_id in run_dirs:
        run_path = os.path.join(input_path, run_id)
        for dirpath, _dirs, files in os.walk(run_path):
            for fn in files:
                fp = os.path.join(dirpath, fn)
                try:
                    if fn.endswith(".xml"):
                        results.extend(parse_junit(fp, run_id))
                    elif fn.endswith(".json"):
                        results.extend(parse_playwright(fp, run_id))
                except (ET.ParseError, json.JSONDecodeError, OSError) as exc:
                    gaps.append(f"skipped unparseable {fp}: {exc}")

    if commit_sha:
        for r in results:
            r.commit_sha = commit_sha

    print(f"NODE_EXIT ingest: parsed {len(results)} results across {len(run_dirs)} runs")
    # Return shape: {"raw_results": [...], "gaps": [...]}.
    return {"raw_results": results, "gaps": gaps}
