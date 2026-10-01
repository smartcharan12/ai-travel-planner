"""Shared pytest fixtures.

Tests never read the developer's real ``.env`` (``_env_file=None``) so they
behave identically on a laptop with keys and in CI without them.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")  # if DeepEval is imported by a test

from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        return Settings(_env_file=None, **overrides)

    return _make


@pytest.fixture
def goa_payload() -> dict[str, Any]:
    """The running example used throughout the docs: 4 days in Goa for a couple."""
    start = date.today() + timedelta(days=30)
    return {
        "destination": "Goa",
        "origin_city": "Bengaluru",
        "num_days": 4,
        "start_date": start.isoformat(),
        "budget": 25000,
        "currency": "INR",
        "num_travelers": 2,
        "preferences": {
            "travel_style": "couple",
            "pace": "moderate",
            "interests": ["beaches", "food", "nightlife"],
            "dietary": [],
            "transport": ["train"],
            "accommodation": "mid_range",
        },
    }


@pytest.fixture
def client(make_settings: Callable[..., Settings]) -> Iterator[TestClient]:
    """API client wired to keyless demo settings (no real providers)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: make_settings(
        llm_provider="fake", search_provider="mock"
    )
    # raise_server_exceptions=False: assert on the 500 JSON body the user
    # would see, instead of the test crashing with the raw exception.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
