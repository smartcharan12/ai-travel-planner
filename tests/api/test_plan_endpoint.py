"""POST /api/v1/plan (Stage 3): itinerary response shape and error mapping through HTTP."""

from __future__ import annotations

import json

from app.api.dependencies import get_planner
from app.llm.client import StructuredLLM
from app.services.travel_planner import TravelPlanner
from tests.fakes import FakeSearchProvider, ScriptedChatModel, goa_draft_json, goa_extraction_json, goa_items


def _llm(script):
    return StructuredLLM(
        ScriptedChatModel(script=script),
        model_name="gemini-test",
        timeout_seconds=5,
        output_retries=1,
        native_json_schema=False,
    )


def _override(client, make_settings, planner_script, **settings):
    client.app.dependency_overrides[get_planner] = lambda: TravelPlanner(
        make_settings(**settings),
        search_provider=FakeSearchProvider(goa_items()),
        research_llm=_llm([json.dumps(goa_extraction_json())]),
        planner_llm=_llm(planner_script),
    )


def test_demo_plan_over_http(client, goa_payload):
    resp = client.post("/api/v1/plan", json=goa_payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "itinerary" and body["data_mode"] == "demo"
    assert len(body["itinerary"]["days"]) == 4
    assert body["budget"]["currency"] == "INR" and body["budget"]["items"]
    assert body["request_id"] == resp.headers["X-Request-ID"]


def test_plan_response_fields(client, make_settings, goa_payload):
    _override(client, make_settings, [json.dumps(goa_draft_json())])
    body = client.post("/api/v1/plan", json=goa_payload).json()
    assert set(body) >= {
        "itinerary",
        "budget",
        "research",
        "sources",
        "search_summary",
        "grounding",
        "warnings",
        "quality",
        "metadata",
        "notice",
        "data_mode",
    }
    assert body["itinerary"]["accommodation"]["hotel_id"] == "H1"


def test_itinerary_that_cannot_be_repaired_is_502(client, make_settings, goa_payload):
    bad = goa_draft_json()
    bad["days"][0]["activities"][0]["place_id"] = "A99"
    _override(client, make_settings, [json.dumps(bad)] * 3, max_repair_attempts=2)
    resp = client.post("/api/v1/plan", json=goa_payload)
    assert resp.status_code == 502
    error = resp.json()["error"]
    assert error["code"] == "ITINERARY_INVALID" and error["details"]["errors"] == ["UNKNOWN_PLACE_ID"]


def test_openapi_documents_both_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    plan = paths["/api/v1/plan"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    research = paths["/api/v1/research"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert plan.endswith("TravelResponse") and research["$ref"].endswith("ResearchResponse")
