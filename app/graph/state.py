"""The shared state object that flows through the LangGraph research workflow.

Each node receives the whole state and returns a *partial* dict with only
the keys it changed; LangGraph merges that into the state.

Some keys use a **reducer** (``operator.add``): the five search nodes run in
parallel and each returns ``{"category_results": [one item]}``. Without a
reducer LangGraph would not know how to combine five simultaneous writes to
the same key; with ``operator.add`` the lists are concatenated.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, TypedDict

from app.llm.client import LLMUsage
from app.research.normalizer import CategoryResults
from app.schemas import (
    BudgetBreakdown,
    CategorySearchSummary,
    GroundingReport,
    Itinerary,
    ItineraryDraft,
    QualityReport,
    ResearchExtraction,
    ResearchQuery,
    ResearchResult,
    SearchHit,
    TravelRequest,
    ValidationIssue,
)


class ResearchState(TypedDict, total=False):
    # input
    request: TravelRequest
    searched_at: datetime
    # prepare_queries
    queries: list[ResearchQuery]
    # search_* nodes (parallel -> reducer)
    category_results: Annotated[list[CategoryResults], operator.add]
    # aggregate_research
    hits: list[SearchHit]
    search_summary: list[CategorySearchSummary]
    search_latency_ms: float
    # any node may add user-facing warnings
    warnings: Annotated[list[str], operator.add]
    # extract_entities, generate_itinerary, repair_itinerary each append one entry
    extraction: ResearchExtraction
    llm_usage: Annotated[list[LLMUsage], operator.add]
    # ground_entities
    research: ResearchResult
    grounding: GroundingReport


class PlannerState(ResearchState, total=False):
    """Research state plus the itinerary-planning keys (Stage 3)."""

    # generate_itinerary / repair_itinerary / optimize_itinerary
    draft: ItineraryDraft
    optimization_notes: list[str]
    optimization_warnings: list[ValidationIssue]
    repair_attempts: int
    # validate_itinerary
    issues: list[ValidationIssue]
    # assemble_itinerary, calculate_budget, quality_check
    itinerary: Itinerary
    budget: BudgetBreakdown
    budget_issues: list[ValidationIssue]
    quality: QualityReport
