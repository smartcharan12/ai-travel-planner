"""What the API sends back: the plan itself, plus errors and ops endpoints."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import Source, StrictModel
from app.schemas.itinerary import BudgetBreakdown, Itinerary
from app.schemas.research import CategorySearchSummary, GroundingReport, ResearchResult, SearchHit


class IssueSeverity(StrEnum):
    ERROR = "error"  # breaks a hard rule -> triggers repair; never shipped as-is
    WARNING = "warning"  # shipped, but shown to the user (e.g. "over budget by 8%")


class ValidationIssue(StrictModel):
    severity: IssueSeverity
    code: str = Field(examples=["UNKNOWN_PLACE_ID", "DUPLICATE_ATTRACTION", "OVER_BUDGET"])
    message: str
    day_number: int | None = None


class QualityReport(StrictModel):
    """Cheap, deterministic quality signals computed on every request.

    These are not a substitute for offline DeepEval runs (Stage 4); they are
    the always-on smoke alarm, the offline evaluation is the full inspection.
    """

    grounded_activity_ratio: float = Field(
        ge=0, le=1, description="Share of activities that reference a researched place."
    )
    sourced_cost_ratio: float = Field(
        ge=0, le=1, description="Share of the budget total (by amount) that comes from source-quoted prices."
    )
    repair_attempts: int = Field(ge=0)
    issues: list[ValidationIssue] = Field(default_factory=list)
    optimization_notes: list[str] = Field(
        default_factory=list, description="Changes the deterministic optimizer made to the LLM's draft."
    )


class PlanMetadata(StrictModel):
    """Operational facts about how this answer was produced (LLM observability)."""

    model: str
    search_provider: str
    llm_calls: int = 0
    input_tokens: int | None = Field(default=None, description="None if the provider did not report it.")
    output_tokens: int | None = None
    search_latency_ms: float | None = None
    llm_latency_ms: float | None = None
    total_latency_ms: float | None = None
    is_demo: bool = Field(description="True when offline stand-ins (fake LLM / mock search) were used.")


class TravelResponse(StrictModel):
    """Stage 3 answer from POST /api/v1/plan: the itinerary plus everything needed to audit it."""

    request_id: str
    stage: Literal["itinerary"] = "itinerary"
    status: Literal["success", "partial"] = Field(
        description="'partial' = plan produced but some research failed (see warnings)."
    )
    data_mode: Literal["live", "demo"]
    notice: str
    itinerary: Itinerary
    budget: BudgetBreakdown
    research: ResearchResult = Field(description="The verified places the itinerary was allowed to use.")
    sources: list[Source]
    search_summary: list[CategorySearchSummary]
    grounding: GroundingReport
    warnings: list[str] = Field(default_factory=list)
    quality: QualityReport
    metadata: PlanMetadata


class ResearchResponse(StrictModel):
    """Answer from POST /api/v1/research: verified research only, no itinerary.

    Shows the whole chain so a reader can audit it:
    queries (search_summary) -> normalized results (search_results)
    -> LLM extraction checked against sources (grounding) -> research.
    """

    request_id: str
    stage: Literal["research"] = "research"
    status: Literal["success", "partial"] = Field(
        description="'partial' = at least one research category failed or returned nothing."
    )
    data_mode: Literal["live", "demo"]
    notice: str = Field(description="Human-readable statement of what this data is (and is not).")
    research: ResearchResult
    search_summary: list[CategorySearchSummary]
    search_results: list[SearchHit]
    grounding: GroundingReport
    warnings: list[str] = Field(default_factory=list)
    next_step: str
    metadata: PlanMetadata


# ---------- Errors ----------
class ErrorBody(StrictModel):
    code: str = Field(examples=["SEARCH_TIMEOUT"])
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(StrictModel):
    """Every non-2xx response has exactly this shape, so clients parse one format."""

    error: ErrorBody


# ---------- Ops endpoints ----------
class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, str] = Field(default_factory=dict)


class VersionResponse(StrictModel):
    name: str
    version: str
    git_sha: str
    environment: str
    llm_provider: str
    llm_model: str
    search_provider: str


class MetricsResponse(StrictModel):
    uptime_seconds: float
    counters: dict[str, int]
    timings_ms: dict[str, dict[str, int | float]]
