# ROADMAP.md — Build checklist

Build order follows the spec: deterministic, independently-testable nodes first; LLM/vector
nodes last. Check items off as you go. Spec references point into `docs/test-data-mining.md`.

## Legend
- [x] done and verified
- [ ] to build
- 🔒 invariant — must hold at every step (read-only, no Neo4j, deterministic-before-LLM)

---

## Milestone 0 — Scaffold  ✅ done
- [x] Project layout, package, requirements
- [x] `state.py` — `AgentState` + dataclasses + `initial_state()`
- [x] `scripts/generate_fixtures.py` — synthetic JUnit/Playwright data + golden labels
- [x] `scripts/score_golden.py` — precision/recall harness against the golden set
- [x] Starter unit tests

## Milestone 1 — Deterministic core  ✅ done (reference impl)
- [x] `ingest` — JUnit XML + Playwright JSON parsers → normalised `TestResult`  (spec §2.3)
- [x] `flaky_detect` — flakiness score + flaky/stable/insufficient_history verdicts  (§1.2 G1)
- [x] Baseline meets targets: flaky precision ≥ 0.85, recall ≥ 0.75  (§1.5)

> Tuning lesson baked in: requiring the minority outcome ≥ 2 separates flaky tests from
> always-failing regressions and from single-blip stable tests. Tune `flaky_score_cutoff`,
> `min_runs_for_flaky`, and `min_minority_fails` against the golden set.

## Milestone 2 — Finish deterministic nodes  ⬜
- [ ] `validate` — empty/corrupt handling, insufficient-history flagging, set `validation_ok`  (§2.3)
- [ ] `suite_health` — confirm pass rate / mean duration / flake rate over the window  (§1.2 G4)
- [ ] `coverage_gap` (MVP) — parse JaCoCo XML / lcov for module-level gaps; honest gap note if
      no coverage reports present. 🔒 Phase-2 requirement linkage = MongoDB refs, **no graph DB**  (§1.2 G2, §2.6)
- [ ] Extend `generate_fixtures.py` to optionally emit JaCoCo/lcov so coverage is testable

## Milestone 3 — Failure clustering (vector, then LLM)  ⬜  (§2.3, §2.6, G3)
- [ ] Normalise failure messages/stacks → signature (strip line numbers, addresses, timestamps)
- [ ] Embed signatures + cluster by cosine similarity in **ChromaDB** (threshold / HDBSCAN) 🔒 vector DB, not graph
- [ ] LLM **labels** each cluster (optionally RAG-grounded on past resolved failures)
- [ ] Verify LLM-claimed root cause against raw data before including (anti-hallucination)
- [ ] Replace the exact-match placeholder grouping in `stubs.py` with the above

## Milestone 4 — Synthesis + persistence  ⬜  (§2.3, G5)
- [ ] `synthesis` — call Hub LLM router (Anthropic default, **not** a standalone key); rank
      findings; write recommendations into a structured report dict
- [ ] `persist` — write report to the **MongoDB** run store 🔒 no Neo4j, no `KG_SIGNAL_*` events

## Milestone 5 — Graph behaviour + autonomy  ⬜  (§2.1, §2.2)
- [ ] `review` HITL via `interrupt()` → `Command(resume=...)`; confirm/filter findings (L2)
- [ ] Conditional routing verified: L1/L3 skip `review`; L2 stops at the gate
- [ ] Swap `MemorySaver` for the platform checkpointer when integrating

## Milestone 6 — Testing & validation  ⬜  (Phase 4)
- [ ] Unit: a test per node (pattern in `tests/test_flaky_detect.py`)
- [ ] Integration: full graph state flow per autonomy level; HITL interrupt/resume; partial-data path
- [ ] Behavioral: golden-set precision/recall/F1 (extend `score_golden.py` to coverage + clusters)
- [ ] Adversarial: corrupt/empty XML, single-run, huge volumes, mixed formats

## Milestone 7 — Deployment & monitoring  ⬜  (Phase 5, Phase 6)
- [ ] FastAPI agent runtime + `manual` trigger (MVP); `schedule` via Celery Beat
- [ ] Per-project archetype config (autonomy / guardrails / triggers)
- [ ] Monitoring: run health, token cost, golden-set regression, data-drift checks; HITL
      corrections feed back into the golden set (closes the ADLC loop)

---

## Open questions to resolve with senior (spec §"Open questions")
1. MVP data sources — JUnit XML + Playwright JSON only, or coverage from day one?
2. CI/CD systems feeding us (Jenkins / GitHub Actions / Azure DevOps) → drives ingest adapters.
3. Requirement-level gaps in v1, or defer to Phase 2? (Either way: no graph DB.)
4. Confirm L2 default autonomy.
5. Flaky threshold: minimum run count *N* and score cutoff.
6. Who curates/owns the labelled golden set.
