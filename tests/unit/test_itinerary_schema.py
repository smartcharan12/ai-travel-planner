"""Itinerary / research schemas: the contract the LLM output must satisfy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    Activity,
    Attraction,
    CostBasis,
    DailyPlan,
    Itinerary,
    ResearchResult,
    Source,
)


def _activity(**overrides):
    data = {
        "slot": "morning",
        "activity_type": "sightseeing",
        "title": "Visit Fort Aguada",
        "description": "17th-century Portuguese fort with sea views.",
        "place_id": "A1",
    }
    return Activity(**{**data, **overrides})


def test_activity_without_price_is_valid():
    act = _activity()
    assert act.estimated_cost is None
    assert act.cost_basis == CostBasis.UNKNOWN


def test_price_without_basis_is_rejected():
    # The model must say where a number came from, or not give one at all.
    with pytest.raises(ValidationError, match="cost_basis"):
        _activity(estimated_cost=500)


def test_price_with_basis_is_valid():
    assert _activity(estimated_cost=500, cost_basis="source").estimated_cost == 500


def test_negative_price_is_rejected():
    with pytest.raises(ValidationError):
        _activity(estimated_cost=-1, cost_basis="estimate")


def test_invented_field_from_llm_is_rejected():
    with pytest.raises(ValidationError, match="Extra inputs"):
        _activity(opening_hours="9am-5pm")


def test_day_needs_at_least_one_activity_and_at_most_six():
    with pytest.raises(ValidationError):
        DailyPlan(day_number=1, theme="Empty", activities=[])
    with pytest.raises(ValidationError):
        DailyPlan(day_number=1, theme="Too much", activities=[_activity()] * 7)


def test_itinerary_round_trips_through_json():
    itin = Itinerary(
        title="4 days in Goa",
        summary="Beaches and food.",
        days=[DailyPlan(day_number=1, theme="North Goa", activities=[_activity()])],
    )
    assert Itinerary.model_validate_json(itin.model_dump_json()) == itin


def test_source_rejects_non_http_urls():
    with pytest.raises(ValidationError, match="http"):
        Source(
            id="S1", title="x", url="javascript:alert(1)", provider="tavily", retrieved_at=datetime.now(UTC)
        )


def test_research_entity_ids():
    research = ResearchResult(
        attractions=[Attraction(id="A1", name="Fort Aguada", description="Fort", source_id="S1")],
        searched_at=datetime.now(UTC),
    )
    assert research.entity_ids() == {"A1"}
