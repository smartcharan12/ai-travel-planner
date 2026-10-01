"""OPTIONAL live tests against the real Tavily and Gemini APIs.

Skipped unless RUN_LIVE_TESTS=1 and the keys are set (in the environment or .env).
They cost real API credits and their results depend on today's web, so they
check *shape and invariants*, never exact content.

    RUN_LIVE_TESTS=1 .venv/bin/pytest tests/live -v
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

import pytest

from app.config import Settings
from app.schemas import ResearchCategory, ResearchQuery, TravelRequest
from app.services.research_planner import ResearchPlanner
from app.tools.search import create_search_provider

pytestmark = pytest.mark.live

_settings = Settings()  # reads .env on purpose: live tests need the developer's real keys
_enabled = os.getenv("RUN_LIVE_TESTS") == "1"


def _skip_unless(*names: str):
    missing = [n for n in names if n in _settings.missing_secrets()] or (
        ["RUN_LIVE_TESTS=1"] if not _enabled else []
    )
    return pytest.mark.skipif(bool(missing) or not _enabled, reason=f"live test needs {missing or names}")


@_skip_unless("TAVILY_API_KEY")
def test_live_tavily_search_returns_goa_results():
    provider = create_search_provider(_settings)
    query = ResearchQuery(category=ResearchCategory.ATTRACTIONS, destination="Goa", text="top beaches in Goa")
    items = asyncio.run(provider.search(query, max_results=3))
    assert items, "Tavily returned no results"
    assert all(i.url.startswith("http") for i in items)


@_skip_unless("TAVILY_API_KEY", "GEMINI_API_KEY")
def test_live_full_goa_research():
    request = TravelRequest(
        destination="Goa",
        origin_city="Bengaluru",
        num_days=4,
        budget=25000,
        num_travelers=2,
        start_date=date.today() + timedelta(days=30),
        preferences={"travel_style": "couple", "interests": ["beaches", "food", "nightlife"]},
    )
    resp = asyncio.run(ResearchPlanner(_settings).run(request, request_id="live-test"))
    assert resp.data_mode == "live"
    hits = {h.source_id for h in resp.search_results}
    entities = [*resp.research.attractions, *resp.research.restaurants, *resp.research.hotels]
    assert entities, "Gemini extracted nothing usable"
    assert all(e.source_id in hits for e in entities)


@_skip_unless("TAVILY_API_KEY", "GEMINI_API_KEY")
def test_live_full_goa_plan():
    from app.services.travel_planner import TravelPlanner

    request = TravelRequest(
        destination="Goa",
        origin_city="Bengaluru",
        num_days=4,
        budget=25000,
        num_travelers=2,
        start_date=date.today() + timedelta(days=30),
        preferences={"travel_style": "couple", "interests": ["beaches", "food", "nightlife"]},
    )
    resp = asyncio.run(TravelPlanner(_settings).run(request, request_id="live-plan"))
    assert resp.data_mode == "live" and len(resp.itinerary.days) == 4
    allowed = resp.research.entity_ids()
    assert all(a.place_id in allowed for d in resp.itinerary.days for a in d.activities if a.place_id)
    assert resp.budget.total == sum(i.amount for i in resp.budget.items)
