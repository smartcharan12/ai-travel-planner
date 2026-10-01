"""Offline demo mode: explicit opt-in, clearly labelled, same code path."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.schemas import TravelRequest
from app.services.research_planner import ResearchPlanner


def test_demo_mode_switches_both_providers(make_settings):
    settings = make_settings(demo_mode=True)
    assert (settings.llm_provider, settings.search_provider) == ("fake", "mock")
    assert settings.is_demo and settings.missing_secrets() == []


@pytest.mark.parametrize("overrides", [{"llm_provider": "fake"}, {"search_provider": "mock"}])
def test_half_demo_configuration_is_rejected(make_settings, overrides):
    with pytest.raises(ValidationError, match="must be used together"):
        make_settings(**overrides)


def test_demo_run_is_labelled_everywhere_and_cites_only_demo_urls(make_settings, goa_payload):
    planner = ResearchPlanner(make_settings(demo_mode=True))
    resp = asyncio.run(planner.run(TravelRequest.model_validate(goa_payload), request_id="r1"))
    assert resp.data_mode == "demo" and resp.metadata.is_demo
    assert resp.notice.startswith("DEMO DATA")
    assert all(s.url.startswith("https://demo.invalid/") for s in resp.research.sources)
    for group in (resp.research.attractions, resp.research.restaurants, resp.research.hotels):
        assert all(e.name.startswith("Sample ") for e in group)


def test_demo_shows_grounding_rejecting_the_planted_hallucination(make_settings, goa_payload):
    planner = ResearchPlanner(make_settings(demo_mode=True))
    resp = asyncio.run(planner.run(TravelRequest.model_validate(goa_payload), request_id="r1"))
    assert [(r.name, r.reason) for r in resp.grounding.rejected] == [
        ("Imaginary Palace", "NAME_NOT_IN_SOURCE")
    ]
    assert "Imaginary Palace" not in [a.name for a in resp.research.attractions]


def test_missing_keys_do_not_silently_fall_back_to_demo(make_settings, goa_payload):
    from app.core.exceptions import ConfigurationError

    planner = ResearchPlanner(make_settings())  # real providers, no keys
    with pytest.raises(ConfigurationError) as info:
        asyncio.run(planner.run(TravelRequest.model_validate(goa_payload), request_id="r1"))
    assert info.value.details == {"missing": ["GEMINI_API_KEY", "TAVILY_API_KEY"]}
