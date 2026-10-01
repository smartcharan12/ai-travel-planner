"""What the API sends back: the plan itself, plus errors and ops endpoints."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import Source, StrictModel
from app.schemas.itinerary import BudgetBreakdown, Itinerary


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

    These are not a substitute for offline DeepEval runs (Stage 3); they are
    the always-on smoke alarm, the offline evaluation is the full inspection.
    """

    grounded_activity_ratio: float = Field(
        ge=0, le=1, description="Share of activities that reference a researched place."
    )
    sourced_cost_ratio: float = Field(
        ge=0, le=1, description="Share of priced items whose price came from a source."
    )
    repair_attempts: int = Field(ge=0)
    issues: list[ValidationIssue] = Field(default_factory=list)


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
    request_id: str
    status: Literal["success", "partial"] = Field(
        description="'partial' = plan produced but some research failed (see warnings)."
    )
    itinerary: Itinerary
    budget: BudgetBreakdown
    sources: list[Source]
    warnings: list[str] = Field(default_factory=list)
    quality: QualityReport
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
