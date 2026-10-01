"""HTTP endpoints, all under the /api/v1 prefix.

Routes stay thin: they validate (automatically, via the Pydantic types in
their signatures), delegate to a service, and shape the response. No
business logic lives here, so the same planner can later be called from a
CLI, a queue worker or a test without going through HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.core.exceptions import PlannerNotReadyError
from app.observability.metrics import metrics
from app.schemas import (
    ErrorResponse,
    HealthResponse,
    MetricsResponse,
    TravelRequest,
    TravelResponse,
    VersionResponse,
)

router = APIRouter(prefix="/api/v1")

# Documented error shapes so they show up in the OpenAPI docs at /docs.
_PLAN_ERRORS = {code: {"model": ErrorResponse} for code in (422, 429, 501, 502, 503, 504, 500)}


@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness: 'is the process up and able to answer HTTP?'

    Deliberately checks nothing external. If Gemini is down, restarting our
    pod would not fix it, so liveness must not depend on it.
    """
    return HealthResponse(status="ok", checks={"process": "ok"})


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse}},
    tags=["ops"],
)
def readiness(settings: Settings = Depends(get_settings)):
    """Readiness: 'should traffic be sent to this instance?'

    Fails (503) when required API keys are missing, so Kubernetes keeps a
    misconfigured pod out of the load balancer instead of serving errors.
    Only variable *names* are reported, never values.
    """
    missing = settings.missing_secrets()
    if missing:
        body = HealthResponse(status="degraded", checks={"config": f"missing: {', '.join(missing)}"})
        return JSONResponse(status_code=503, content=body.model_dump())
    return HealthResponse(status="ok", checks={"config": "ok"})


@router.get("/version", response_model=VersionResponse, tags=["ops"])
def version(settings: Settings = Depends(get_settings)) -> VersionResponse:
    """Which build is running and which providers it is configured for."""
    return VersionResponse(
        name=settings.app_name,
        version=settings.app_version,
        git_sha=settings.git_sha,
        environment=settings.app_env,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        search_provider=settings.search_provider,
    )


@router.get("/metrics", response_model=MetricsResponse, tags=["ops"])
def get_metrics() -> MetricsResponse:
    """Counters and latency stats for THIS process (see observability/metrics.py)."""
    return MetricsResponse(**metrics.snapshot())


@router.post(
    "/plan",
    response_model=TravelResponse,
    responses=_PLAN_ERRORS,
    tags=["planner"],
)
def create_plan(
    travel_request: TravelRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> TravelResponse:
    """Generate a researched, validated, budgeted itinerary.

    By the time this function runs, FastAPI has already parsed the JSON body
    into a ``TravelRequest`` and rejected anything invalid with a 422.

    Stage 1: validation only. Stage 2 replaces the raise below with a call to
    the LangGraph planning workflow.
    """
    raise PlannerNotReadyError(details={"destination": travel_request.destination})
