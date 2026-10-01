"""Helpers shared by ResearchPlanner (/research) and TravelPlanner (/plan)."""

from __future__ import annotations

from datetime import datetime

from app.config import Settings
from app.core.exceptions import ConfigurationError
from app.demo.data import DEMO_NOTICE
from app.llm.client import StructuredLLM
from app.llm.factory import create_structured_llm
from app.observability.context import current_stats
from app.schemas import TravelRequest
from app.tools.search import SearchProvider, create_search_provider


def require_configuration(settings: Settings) -> None:
    """Fail with the names (never values) of missing keys. No silent fallback to demo data."""
    missing = settings.missing_secrets()
    if missing:
        raise ConfigurationError(details={"missing": missing})


def resolve_search(settings: Settings, injected: SearchProvider | None) -> SearchProvider:
    return injected or create_search_provider(settings)


def resolve_llm(settings: Settings, injected: StructuredLLM | None, *, temperature: float) -> StructuredLLM:
    return injected or create_structured_llm(settings, temperature=temperature)


def annotate_request(
    request: TravelRequest, *, stage: str, demo_mode: bool, model: str, search_provider: str
) -> None:
    """Fill the per-request stats that the middleware writes into ``request_completed``."""
    stats = current_stats()
    if stats is None:
        return
    stats.destination = request.destination
    stats.stage = stage
    stats.demo_mode = demo_mode
    stats.model = model
    stats.search_provider = search_provider


def data_notice(is_demo: bool, searched_at: datetime, provider_name: str) -> str:
    if is_demo:
        return DEMO_NOTICE
    return (
        f"Live research retrieved {searched_at:%Y-%m-%d %H:%M} UTC via {provider_name}. "
        "Web sources can be wrong or out of date: verify prices and opening hours before booking."
    )
