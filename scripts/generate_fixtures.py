#!/usr/bin/env python3
"""
generate_fixtures.py — Synthetic test-execution data for the Test Data Mining Agent.

Why this exists
---------------
No public dataset (Kaggle CI/CD logs, IDoFT, FlakeFlagger) ships data in the *raw* format
this agent ingests (JUnit/TestNG XML + Playwright JSON, with pass/fail history across runs)
AND with a clean ground-truth label of which tests are flaky. So we synthesise it. Because
we control the generator, we know exactly which tests are flaky/stable/always-failing — that
labelled ground truth becomes the Phase-4 golden set we score precision/recall against.

What it produces (stdlib only — no pip installs needed)
-------------------------------------------------------
  data/fixtures/run_<NN>/junit/results.xml      JUnit XML per run
  data/fixtures/run_<NN>/playwright/results.json Playwright JSON per run
  data/golden/flaky_labels.json                  ground truth: {test_id: "flaky"|"stable"|"always_fail"}
  data/golden/manifest.json                      run metadata (commit shas, seeds, counts)

Test "personas" we seed
------------------------
  * stable      — passes ~always (rare infra blip allowed)
  * flaky       — passes/fails non-deterministically at the SAME commit (the target signal)
  * always_fail — a real regression (fails every run) — must NOT be labelled flaky
  * slow        — stable but high duration (feeds suite-health trend)

Usage
-----
  python scripts/generate_fixtures.py                 # defaults: 8 runs, 40 tests
  python scripts/generate_fixtures.py --runs 12 --tests 60 --seed 7
"""
from __future__ import annotations

import argparse
import json
import os
import random
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# Test catalogue: (test_id, suite, persona, base_duration_sec)
# --------------------------------------------------------------------------- #
SUITES = ["auth", "checkout", "search", "profile", "payments"]

FAILURE_SIGNATURES = {
    "flaky": [
        ("TimeoutError: waiting for selector exceeded 5000ms",
         "  at Page.waitForSelector (pw/page.js:812)\n  at CheckoutTest.run (checkout.spec.ts:44)"),
        ("AssertionError: expected element to be visible",
         "  at Assertions.toBeVisible (expect.js:201)\n  at SearchTest.run (search.spec.ts:73)"),
        ("ConnectionResetError: connection reset by peer",
         "  at Socket._read (net.js:644)\n  at AuthTest.login (auth.spec.ts:29)"),
    ],
    "always_fail": [
        ("AssertionError: expected status 200 but got 500",
         "  at ApiClient.assertOk (client.js:90)\n  at PaymentsTest.charge (payments.spec.ts:118)"),
    ],
}


def build_catalogue(n_tests: int, rng: random.Random) -> list[dict]:
    """Create a deterministic-ish catalogue of tests with assigned personas."""
    catalogue = []
    # Fixed proportions so the golden set is balanced and realistic.
    n_flaky = max(3, round(n_tests * 0.15))
    n_always_fail = max(1, round(n_tests * 0.05))
    n_slow = max(2, round(n_tests * 0.10))
    personas = (
        ["flaky"] * n_flaky
        + ["always_fail"] * n_always_fail
        + ["slow"] * n_slow
    )
    personas += ["stable"] * (n_tests - len(personas))
    rng.shuffle(personas)

    for i, persona in enumerate(personas):
        suite = SUITES[i % len(SUITES)]
        test_id = f"com.example.{suite}.{suite.capitalize()}Test#test_case_{i:03d}"
        base_duration = round(rng.uniform(0.05, 0.9), 3)
        if persona == "slow":
            base_duration = round(rng.uniform(4.0, 9.0), 3)
        catalogue.append(
            {"test_id": test_id, "suite": suite, "persona": persona, "base_duration": base_duration}
        )
    return catalogue


def outcome_for(persona: str, rng: random.Random) -> str:
    """Decide a single run outcome for a test given its persona."""
    if persona == "always_fail":
        return "failed"
    if persona == "flaky":
        # ~30% fail rate at the same commit — the defining flaky behaviour.
        return "failed" if rng.random() < 0.30 else "passed"
    # stable / slow: very rare infra blip (2%) so detectors must tolerate noise.
    return "failed" if rng.random() < 0.02 else "passed"


def duration_for(base: float, persona: str, rng: random.Random) -> float:
    jitter = rng.uniform(-0.1, 0.25) * base
    return round(max(0.01, base + jitter), 3)


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #
def write_junit(path: str, suite_name: str, rows: list[dict], ts: str) -> None:
    testsuite = ET.Element("testsuite", {
        "name": suite_name,
        "tests": str(len(rows)),
        "failures": str(sum(1 for r in rows if r["outcome"] == "failed")),
        "skipped": "0",
        "timestamp": ts,
    })
    for r in rows:
        classname, _, name = r["test_id"].partition("#")
        case = ET.SubElement(testsuite, "testcase", {
            "classname": classname,
            "name": name,
            "time": f"{r['duration_sec']:.3f}",
        })
        if r["outcome"] == "failed":
            failure = ET.SubElement(case, "failure", {"message": r["message"] or "test failed"})
            failure.text = r["stack_trace"] or ""
    tree = ET.ElementTree(testsuite)
    ET.indent(tree, space="  ")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def write_playwright(path: str, rows: list[dict], ts: str, run_id: str) -> None:
    """Minimal but realistic Playwright JSON reporter shape."""
    specs = []
    for r in rows:
        specs.append({
            "title": r["test_id"],
            "ok": r["outcome"] == "passed",
            "tests": [{
                "status": "expected" if r["outcome"] == "passed" else "unexpected",
                "results": [{
                    "status": r["outcome"],
                    "duration": int(r["duration_sec"] * 1000),
                    "error": None if r["outcome"] == "passed"
                             else {"message": r["message"], "stack": r["stack_trace"]},
                }],
            }],
        })
    doc = {
        "config": {"metadata": {"run_id": run_id, "timestamp": ts}},
        "suites": [{"title": "playwright-suite", "specs": specs}],
        "stats": {
            "expected": sum(1 for r in rows if r["outcome"] == "passed"),
            "unexpected": sum(1 for r in rows if r["outcome"] == "failed"),
        },
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic test-execution fixtures.")
    ap.add_argument("--runs", type=int, default=10, help="number of CI runs to simulate")
    ap.add_argument("--tests", type=int, default=40, help="number of distinct tests")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    ap.add_argument("--out", default=None, help="output root (default: <repo>/data)")
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_root = args.out or os.path.join(repo_root, "data")
    fixtures_dir = os.path.join(out_root, "fixtures")
    golden_dir = os.path.join(out_root, "golden")
    os.makedirs(golden_dir, exist_ok=True)

    rng = random.Random(args.seed)
    catalogue = build_catalogue(args.tests, rng)

    # All runs share ONE commit_sha so flaky != real regression is detectable.
    commit_sha = f"{rng.getrandbits(40):010x}"
    base_time = datetime(2026, 1, 1, 2, 0, 0, tzinfo=timezone.utc)

    manifest = {"commit_sha": commit_sha, "seed": args.seed, "runs": [], "n_tests": args.tests}

    for run_idx in range(args.runs):
        run_id = f"run_{run_idx:02d}"
        ts = (base_time + timedelta(days=run_idx)).isoformat()
        rows = []
        for t in catalogue:
            outcome = outcome_for(t["persona"], rng)
            msg, stack = (None, None)
            if outcome == "failed":
                bucket = "always_fail" if t["persona"] == "always_fail" else "flaky"
                msg, stack = rng.choice(FAILURE_SIGNATURES[bucket])
            rows.append({
                "test_id": t["test_id"],
                "outcome": outcome,
                "duration_sec": duration_for(t["base_duration"], t["persona"], rng),
                "message": msg,
                "stack_trace": stack,
            })

        # Split across the two source formats (half each) to exercise both parsers.
        mid = len(rows) // 2
        write_junit(os.path.join(fixtures_dir, run_id, "junit", "results.xml"),
                    "junit-suite", rows[:mid], ts)
        write_playwright(os.path.join(fixtures_dir, run_id, "playwright", "results.json"),
                         rows[mid:], ts, run_id)
        manifest["runs"].append({"run_id": run_id, "timestamp": ts, "tests": len(rows)})

    # Ground-truth golden labels (persona -> label the agent should recover)
    label_map = {"flaky": "flaky", "always_fail": "always_fail", "stable": "stable", "slow": "stable"}
    golden = {t["test_id"]: label_map[t["persona"]] for t in catalogue}
    with open(os.path.join(golden_dir, "flaky_labels.json"), "w", encoding="utf-8") as f:
        json.dump(golden, f, indent=2, sort_keys=True)
    with open(os.path.join(golden_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    n_flaky = sum(1 for v in golden.values() if v == "flaky")
    n_fail = sum(1 for v in golden.values() if v == "always_fail")
    print(f"Generated {args.runs} runs x {args.tests} tests at commit {commit_sha}")
    print(f"  fixtures -> {fixtures_dir}")
    print(f"  golden   -> {golden_dir}/flaky_labels.json")
    print(f"  ground truth: {n_flaky} flaky, {n_fail} always-fail, "
          f"{args.tests - n_flaky - n_fail} stable")


if __name__ == "__main__":
    main()
