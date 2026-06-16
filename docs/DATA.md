# DATA.md — Data sourcing for the Test Data Mining Agent

## TL;DR

There is **no public dataset in the exact raw format this agent ingests** (JUnit/TestNG XML +
Playwright JSON, *with pass/fail history across runs*) **and** with clean ground-truth flaky
labels. So we **generate our own fixtures** with `scripts/generate_fixtures.py`. Because we
control the generator, we know exactly which tests are flaky — that labelled ground truth is
our Phase-4 golden set. Public datasets (below) are useful later for realism, not for the MVP.

```bash
python scripts/generate_fixtures.py            # default: 10 runs x 40 tests
python scripts/generate_fixtures.py --runs 15 --tests 80 --seed 7
python scripts/score_golden.py                 # measure precision/recall vs ground truth
```

## What the agent actually needs

| Need | Format | Where it comes from |
|------|--------|---------------------|
| Per-test outcomes per run | JUnit/TestNG XML, Playwright JSON | generated fixtures (`data/fixtures/run_*/`) |
| Pass/fail history across runs | several runs at the **same** commit | the generator emits ≥10 runs at one commit_sha |
| Ground-truth flaky labels | label per test | `data/golden/flaky_labels.json` |
| Failure messages + stacks | text on failed cases | generated, drawn from a small signature pool |
| Coverage reports | JaCoCo XML / lcov | **Phase 2** — not in MVP fixtures yet |

## What the generator produces

```
data/fixtures/run_00..run_NN/
    junit/results.xml         # ~half the tests, JUnit XML
    playwright/results.json   # ~half the tests, Playwright JSON
data/golden/
    flaky_labels.json         # {test_id: "flaky" | "stable" | "always_fail"}
    manifest.json             # commit_sha, seed, run metadata
```

Four seeded test "personas" give the detectors something real to find:

- **flaky** — fails ~30% of runs at the same commit (the target signal).
- **always_fail** — fails every run (a real regression; must **not** be labelled flaky).
- **slow** — stable but high duration (feeds suite-health trend).
- **stable** — passes almost always (a rare ~2% infra blip is included on purpose, so the
  detector has to tolerate noise rather than over-flag).

The `always_fail` persona is the important trap: a naive detector that flags "anything that
ever fails" will mislabel regressions as flaky. Our detector requires **both** outcomes and a
minority count ≥ 2, so it separates the two correctly.

## Public datasets (for later realism — optional)

These are good once you want real-world failure messages or to benchmark against external
labels. None replaces the generator for the MVP because of the format/label mismatch noted above.

| Dataset | What it is | Best use here |
|---------|-----------|---------------|
| **IDoFT** (International Dataset of Flaky Tests), `TestingResearchIllinois/idoft` | Java + Python flaky tests with detection/fix metadata (`pr-data.csv`, `gr-data.csv`, `py-data.csv`) | seed realistic flaky test names + categories into the golden set |
| **FlakeFlagger** (`uOttawa-Nanda-Lab/Flakify`) | test code with flaky / non-flaky ground-truth labels | external benchmark for a classifier-style detector |
| **Kaggle: CI/CD Pipeline Failure Logs** (`mirzayasirabdullah07/...`) | ~60k rows, 28 cols of aggregated CI run features | realistic failure-rate / duration distributions to tune the generator |

> Note: this container has no network access, so the datasets above can't be downloaded here.
> Pull them in your own environment if/when you want real-world realism. The generator is the
> dependency-free path that works immediately.

## Suggested next step on data

1. Use generated fixtures to build and validate every node (works offline, deterministic).
2. When detectors are stable, sample real failure messages from IDoFT/Kaggle to enrich the
   `FAILURE_SIGNATURES` pool in the generator so clustering is tested on realistic text.
3. For the pilot, point `ingest` at one real project's CI output and have a QA lead hand-label
   a small golden set (spec open question #6 — golden-set ownership).
