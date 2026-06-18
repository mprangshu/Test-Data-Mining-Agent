"""
state.py — AgentState for the Test Data Mining Agent (v2: test-data generation).

The single source of truth for what flows through the graph. Every node receives an
``AgentState`` and returns a dict of only the keys it updates. See docs/TDM-PIVOT-v2.md §4.

Pipeline that fills these keys:
    parse → [load_results | mongo_lookup | vector_search] → coverage_gap
          → generate → review (HITL) → synthesise → persist

Autonomy: this agent runs at ONE level — **L2 · Supervised**. The HITL review gate ALWAYS
runs (no L1/L3 toggle). The only other human decision is the explicit save gate in `persist`.

Invariants (CLAUDE.md): read-before-write on MongoDB · no Neo4j · deterministic-before-LLM ·
graceful degradation (nodes append to `gaps`/`errors`, never crash) · anti-hallucination.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, TypedDict


ScenarioType = Literal["valid", "boundary", "negative", "edge"]


# ── Primary input: parsed test cases ──────────────────────────────────
@dataclass
class ParsedField:
    name: str                          # "email"
    category: str                      # "Identity" | "PII" | "Financial" | ...
    constraints: list[str]             # ["required", "ISO-4217"] etc.
    source_test_ids: list[str]         # which test cases need this field
    scenario_types: list[str]          # which scenarios reference it


# ── Supporting input: signals from result files ───────────────────────
@dataclass
class ResultSignal:
    test_case_id: str
    scenario_tag: str                  # e.g. "typical_order", "missing_email"
    scenario_type: str                 # valid | boundary | negative | edge
    outcome: Literal["passed", "failed", "skipped", "error"]
    fields_exercised: list[str]        # field names this test touched


@dataclass
class SeedValue:
    field_name: str
    example_values: list[Any]          # real values from PASSING runs (few-shot seeds)


# ── Gathered data ─────────────────────────────────────────────────────
@dataclass
class ExistingRecord:
    test_case_id: str
    label: str
    tags: list[str]
    fields: dict[str, list[Any]]       # field → stored values


@dataclass
class RetrievedRecord:
    test_case_id: str
    similarity_score: float
    fields: dict[str, list[Any]]


@dataclass
class CoverageGap:
    field_name: str
    scenario_type: str                 # the scenario that was never exercised
    reason: str                        # "no negative-case value tested for email"


# ── Candidate sets (what generate produces, what HITL chooses from) ───
@dataclass
class CandidateSet:
    set_id: str                        # "gen_A" | "gen_B" | "existing" | "retrieved"
    source: Literal["generated", "existing", "retrieved"]
    values: list[Any]                  # the actual values in this set
    scenario_coverage: list[str]       # which scenario types this set covers
    note: str                          # short rationale ("boundary-heavy variant")


@dataclass
class FieldCandidates:
    field_name: str
    category: str
    sets: list[CandidateSet]           # 2–3 generated + maybe existing + retrieved
    gap_flagged: bool                  # True if this field had a coverage gap


# ── HITL decision (set-level, per field) ──────────────────────────────
@dataclass
class ReviewSelection:
    field_name: str
    include: bool
    chosen_set_id: Optional[str]       # which CandidateSet the analyst kept
    custom_values: Optional[list[Any]] = None   # if analyst typed their own


# ── The graph state ───────────────────────────────────────────────────
class AgentState(TypedDict, total=False):
    input_path: str

    parsed_fields: list[ParsedField]            # parse
    input_rows: list[dict[str, Any]]            # parse — original uploaded rows, VERBATIM
    input_columns: list[str]                    # parse — exact uploaded column names/order
    input_row_count: int                        # parse — len(input_rows), for the always-larger guard
    result_signals: list[ResultSignal]          # load_results
    seed_values: list[SeedValue]                # load_results
    existing_data: list[ExistingRecord]         # mongo_lookup
    retrieved_data: list[RetrievedRecord]       # vector_search
    coverage_gaps: list[CoverageGap]            # coverage_gap
    candidate_sets: list[FieldCandidates]       # generate

    review_selections: list[ReviewSelection]    # review (HITL)

    final_dataset: list[dict[str, Any]]         # synthesise
    report: Optional[dict[str, Any]]            # synthesise

    persist_decision: Optional[bool]            # /persist
    persist_label: Optional[str]
    persist_tags: Optional[list[str]]
    persist_receipt: Optional[dict[str, Any]]

    # graceful degradation — operator.add reducers so notes accumulate across nodes
    # (and parallel data-gather nodes can write them without an InvalidUpdateError).
    gaps: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]


def initial_state(input_path: str) -> AgentState:
    """Build a fresh state with v2 defaults (always L2 · HITL)."""
    return AgentState(
        input_path=input_path,
        parsed_fields=[],
        input_rows=[],
        input_columns=[],
        input_row_count=0,
        result_signals=[],
        seed_values=[],
        existing_data=[],
        retrieved_data=[],
        coverage_gaps=[],
        candidate_sets=[],
        review_selections=[],
        final_dataset=[],
        report=None,
        persist_decision=None,
        persist_label=None,
        persist_tags=None,
        persist_receipt=None,
        gaps=[],
        errors=[],
    )
