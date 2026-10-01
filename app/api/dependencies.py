"""FastAPI dependencies: how routes obtain services.

Routes ask for a planner with ``Depends(get_planner)``; tests swap it via
``app.dependency_overrides[get_planner] = lambda: TravelPlanner(settings, search_provider=fake, ...)``.
Building a planner never raises: missing keys are reported when it runs, which
is *after* FastAPI has validated the request body, so invalid input still gets 422.
"""

from __future__ import annotations

from fastapi import Depends

from app.config import Settings, get_settings
from app.services.research_planner import ResearchPlanner
from app.services.travel_planner import TravelPlanner


def get_planner(settings: Settings = Depends(get_settings)) -> TravelPlanner:
    return TravelPlanner(settings)


def get_research_planner(settings: Settings = Depends(get_settings)) -> ResearchPlanner:
    return ResearchPlanner(settings)
