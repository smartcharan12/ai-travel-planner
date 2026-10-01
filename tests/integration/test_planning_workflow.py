"""The full Stage 3 graph (research -> plan -> validate/repair -> budget) with faked providers."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.exceptions import ItineraryValidationError, LLMOutputError, NoResearchResultsError
from app.llm.client import StructuredLLM
from app.schemas import TravelRequest
from app.services.travel_planner import TravelPlanner
from tests.fakes import FakeSearchProvider, ScriptedChatModel, goa_draft_json, goa_extraction_json, goa_items


def _llm(script, usage=None) -> StructuredLLM:
    return StructuredLLM(
        ScriptedChatModel(script=script, usage=usage),
        model_name="gemini-test",
        timeout_seconds=5,
        output_retries=1,
        native_json_schema=False,
    )


def _bad_draft(place_id="A99"):
    data = goa_draft_json()
    data["days"][0]["activities"][0]["place_id"] = place_id
    return json.dumps(data)


def _plan(make_settings, goa_payload, planner_script, extraction=None, **settings):
    planner = TravelPlanner(
        make_settings(**settings),
        search_provider=FakeSearchProvider(goa_items()),
        research_llm=_llm(
            [json.dumps(extraction or goa_extraction_json())],
            usage={"input_tokens": 2000, "output_tokens": 400, "total_tokens": 2400},
        ),
        planner_llm=_llm(
            planner_script, usage={"input_tokens": 1500, "output_tokens": 800, "total_tokens": 2300}
        ),
    )
    return asyncio.run(planner.run(TravelRequest.model_validate(goa_payload), request_id="req-plan"))


def test_valid_first_draft_produces_full_response(make_settings, goa_payload):
    resp = _plan(make_settings, goa_payload, [json.dumps(goa_draft_json())])
    assert resp.stage == "itinerary" and resp.data_mode == "live"
    assert [d.day_number for d in resp.itinerary.days] == [1, 2, 3, 4]
    assert resp.quality.repair_attempts == 0
    # every scheduled place id is a verified entity, traceable to a source URL
    entities = resp.research.entity_index()
    sources = {s.id: s.url for s in resp.sources}
    for day in resp.itinerary.days:
        for a in day.activities:
            if a.place_id:
                assert sources[entities[a.place_id].source_id].startswith("https://")
    # LLM usage summed over extraction + planning
    assert resp.metadata.llm_calls == 2
    assert (resp.metadata.input_tokens, resp.metadata.output_tokens) == (3500, 1200)
    assert resp.budget.total > 0 and resp.budget.items


def test_invalid_draft_is_repaired_once(make_settings, goa_payload):
    resp = _plan(make_settings, goa_payload, [_bad_draft(), json.dumps(goa_draft_json())])
    assert resp.quality.repair_attempts == 1
    assert resp.itinerary.days[0].activities[0].place_id == "A1"
    assert resp.metadata.llm_calls == 3


def test_repair_attempts_are_bounded(make_settings, goa_payload):
    script = [_bad_draft(), _bad_draft(), _bad_draft("H1")]  # first + 2 repairs, all invalid
    with pytest.raises(ItineraryValidationError) as info:
        _plan(make_settings, goa_payload, script, max_repair_attempts=2)
    assert info.value.details == {"repair_attempts": 2, "errors": ["HOTEL_AS_ACTIVITY"]}


def test_zero_repairs_configured_fails_immediately(make_settings, goa_payload):
    with pytest.raises(ItineraryValidationError):
        _plan(make_settings, goa_payload, [_bad_draft()], max_repair_attempts=0)


def test_no_verified_places_stops_before_planning(make_settings, goa_payload):
    extraction = goa_extraction_json()
    extraction["attractions"] = []
    extraction["restaurants"] = []
    with pytest.raises(NoResearchResultsError):
        _plan(make_settings, goa_payload, [], extraction=extraction)  # planner never called


def test_malformed_planner_output_fails_cleanly(make_settings, goa_payload):
    with pytest.raises(LLMOutputError):
        _plan(make_settings, goa_payload, ["not json", "{still not json"])


def test_demo_mode_plan_shows_repair_loop(make_settings, goa_payload):
    resp = asyncio.run(
        TravelPlanner(make_settings(demo_mode=True)).run(TravelRequest.model_validate(goa_payload), "demo")
    )
    assert resp.data_mode == "demo" and resp.notice.startswith("DEMO DATA")
    assert resp.quality.repair_attempts == 1  # demo planner plants 'A99' on purpose
    assert resp.metadata.llm_calls == 3
    assert all(s.url.startswith("https://demo.invalid/") for s in resp.sources)
    assert len(resp.itinerary.days) == 4
