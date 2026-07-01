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
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, TypedDict


ScenarioType = Literal["valid", "boundary", "negative", "edge"]
# Per-row provenance (UI metadata, NEVER a CSV column): where each output row came from.
RowSource = Literal["input", "generated", "fetched", "gathered"]


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
    fields: dict[str, list[Any]]       # field → stored values (column-oriented)
    rows: list[dict] = field(default_factory=list)   # row-aligned records (coherent), when available


@dataclass
class RetrievedRecord:
    test_case_id: str
    similarity_score: float
    fields: dict[str, list[Any]]
    rows: list[dict] = field(default_factory=list)   # row-aligned records (coherent), when available


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


# ── Output row with provenance (CONTEXT-v3 §3) ────────────────────────
@dataclass
class OutputRow:
    fields: dict[str, Any]             # ONLY the uploaded columns → values (the clean CSV content)
    source: str                        # "input" | "generated" | "fetched" | "gathered" (UI-only)
    row_uid: str                       # stable id so the UI can reference a row back to the agent


# ── The graph state ───────────────────────────────────────────────────
class AgentState(TypedDict, total=False):
    input_path: str

    # Populated by `parse`:
    parsed_fields: list[ParsedField]            # list[ParsedField]
    input_rows: list[dict[str, Any]]            # original uploaded rows (verbatim)
    input_columns: list[str]                    # exact uploaded column names/order
    input_row_count: int                        # len(input_rows)

    # Populated by `load_results`:
    result_signals: list[ResultSignal]          # signals extracted from supporting test results
    seed_values: list[SeedValue]                # few-shot seeds from passing results

    # Populated by data-gather nodes:
    existing_data: list[ExistingRecord]         # mongo_lookup -> ExistingRecord entries
    retrieved_data: list[RetrievedRecord]       # vector_search -> RetrievedRecord entries
    coverage_gaps: list[CoverageGap]            # coverage_gap -> missing scenario coverage
    candidate_sets: list[FieldCandidates]       # generate -> lists of CandidateSet per field

    # Populated by reviewer (HITL):
    review_selections: list[ReviewSelection]    # review outputs selected CandidateSet ids

    # Populated by synthesise:
    final_dataset: list[dict[str, Any]]         # clean rows (fields only) for CSV export
    output_rows: list[OutputRow]                # rows WITH provenance for UI/API
    report: Optional[dict[str, Any]]            # human-readable summary & metrics

    # Iteration + user choices:
    round_index: int                            # which round of generation we're on
    seed_selection: list[dict[str, Any]]        # user-picked rows for the next round

    # Persist decision populated by frontend / backend persist endpoint
    persist_decision: Optional[bool]
    persist_label: Optional[str]
    persist_tags: Optional[list[str]]
    persist_receipt: Optional[dict[str, Any]]

    # graceful degradation — string notes/errors collected across nodes (operator.add reducers)
    gaps: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]


def initial_state(input_path: str) -> AgentState:
    """Build a fresh state with v2 defaults (always L2 · HITL)."""
    # Return the initial AgentState for a new session, with all batched fields empty.
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
        output_rows=[],
        round_index=0,
        seed_selection=[],
        report=None,
        persist_decision=None,
        persist_label=None,
        persist_tags=None,
        persist_receipt=None,
        gaps=[],
        errors=[],
    )
