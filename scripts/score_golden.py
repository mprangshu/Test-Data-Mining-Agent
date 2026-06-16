#!/usr/bin/env python3
"""
score_golden.py — Score the deterministic flaky detector against the golden set.

This is the Phase-4 behavioral/accuracy harness in miniature (spec §1.5, §4). It runs
ingest -> flaky_detect over the generated fixtures, compares the agent's verdicts to the
ground-truth labels in data/golden/flaky_labels.json, and prints precision / recall.

Spec targets: flaky precision >= 0.85, recall >= 0.75.

Run (after generating fixtures):
    python scripts/score_golden.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from test_data_mining.state import initial_state, AutonomyLevel  # noqa: E402
from test_data_mining.nodes.ingest import ingest                 # noqa: E402
from test_data_mining.nodes.flaky_detect import flaky_detect     # noqa: E402


def main() -> int:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixtures = os.path.join(repo, "data", "fixtures")
    golden_path = os.path.join(repo, "data", "golden", "flaky_labels.json")

    if not os.path.isdir(fixtures) or not os.path.exists(golden_path):
        print("Missing fixtures or golden labels. Run scripts/generate_fixtures.py first.")
        return 1

    with open(golden_path, encoding="utf-8") as f:
        golden = json.load(f)

    state = initial_state(fixtures, autonomy_level=AutonomyLevel.L1_ASSISTIVE)
    state.update(ingest(state))
    state.update(flaky_detect(state))

    predicted_flaky = {f.test_id for f in state["flaky_findings"] if f.verdict == "flaky"}
    actual_flaky = {tid for tid, label in golden.items() if label == "flaky"}

    tp = len(predicted_flaky & actual_flaky)
    fp = len(predicted_flaky - actual_flaky)
    fn = len(actual_flaky - predicted_flaky)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    print(f"\nGolden-set evaluation ({len(golden)} tests, {len(actual_flaky)} truly flaky)")
    print(f"  predicted flaky : {len(predicted_flaky)}")
    print(f"  true positives  : {tp}")
    print(f"  false positives : {fp}")
    print(f"  false negatives : {fn}")
    print(f"  precision       : {precision:.3f}  (target >= 0.85)")
    print(f"  recall          : {recall:.3f}  (target >= 0.75)")
    ok = precision >= 0.85 and recall >= 0.75
    print(f"  RESULT          : {'PASS' if ok else 'BELOW TARGET (tune cutoff / N / more runs)'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
