"""Frontend: API client (HTTP mocked), presenters, and the Streamlit script run headless with AppTest."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.config import Settings
from app.schemas import TravelRequest
from app.services.travel_planner import TravelPlanner
from frontend import api_client
from frontend.presenters import activity_line, budget_rows, build_payload, md_escape, place_rows

APP = str(Path(__file__).resolve().parents[2] / "frontend" / "app.py")


@pytest.fixture(scope="module")
def demo_response() -> dict:
    """A real TravelResponse produced by the backend in DEMO mode (no network)."""
    request = TravelRequest(
        destination="Goa",
        origin_city="Bengaluru",
        num_days=3,
        budget=25000,
        num_travelers=2,
        preferences={"travel_style": "couple", "interests": ["beaches", "food"]},
    )
    planner = TravelPlanner(Settings(_env_file=None, demo_mode=True))
    return asyncio.run(planner.run(request, "ui-test")).model_dump(mode="json")


# ---------- api_client ----------
def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_plan_trip_returns_json_on_200(demo_response):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=demo_response)

    result = api_client.plan_trip("http://api:8000/", {"destination": "Goa"}, client=_client(handler))
    assert seen["url"] == "http://api:8000/api/v1/plan"
    assert result["stage"] == "itinerary"


def test_plan_trip_maps_api_errors():
    body = {"error": {"code": "SEARCH_TIMEOUT", "message": "slow", "request_id": "r1", "details": {}}}
    with pytest.raises(api_client.PlannerAPIError) as info:
        api_client.plan_trip("http://x", {}, client=_client(lambda r: httpx.Response(504, json=body)))
    assert (info.value.code, info.value.status, info.value.request_id) == ("SEARCH_TIMEOUT", 504, "r1")


@pytest.mark.parametrize(
    "exc,code",
    [(httpx.ConnectError("refused"), "API_UNREACHABLE"), (httpx.ReadTimeout("slow"), "CLIENT_TIMEOUT")],
)
def test_plan_trip_network_failures(exc, code):
    def handler(request):
        raise exc

    with pytest.raises(api_client.PlannerAPIError) as info:
        api_client.plan_trip("http://x", {}, client=_client(handler))
    assert info.value.code == code


def test_plan_trip_non_json_error():
    with pytest.raises(api_client.PlannerAPIError) as info:
        api_client.plan_trip(
            "http://x", {}, client=_client(lambda r: httpx.Response(502, text="Bad Gateway"))
        )
    assert info.value.code == "UNEXPECTED_RESPONSE"


# ---------- presenters ----------
def test_build_payload_merges_interests_and_omits_blank_optional_fields():
    payload = build_payload(
        destination=" Goa ",
        origin_city="",
        num_days=4,
        start_date=None,
        budget=25000,
        currency="INR",
        num_travelers=2,
        travel_style="couple",
        pace="moderate",
        interests=["beaches"],
        extra_interests="street food, , jazz",
        dietary=[],
        transport=[],
        accommodation="mid_range",
        special_requirements="  ",
    )
    assert payload["destination"] == "Goa" and "origin_city" not in payload and "start_date" not in payload
    assert payload["preferences"]["interests"] == ["beaches", "street food", "jazz"]
    assert payload["preferences"]["transport"] == ["any"]
    assert payload["preferences"]["special_requirements"] is None


def test_build_payload_with_start_date():
    payload = build_payload(
        destination="Goa",
        origin_city="Pune",
        num_days=2,
        start_date=date(2026, 12, 1),
        budget=1,
        currency="INR",
        num_travelers=1,
        travel_style="solo",
        pace="relaxed",
        interests=[],
        extra_interests="",
        dietary=["vegan"],
        transport=["bus"],
        accommodation="hostel",
        special_requirements="",
    )
    assert payload["start_date"] == "2026-12-01" and payload["origin_city"] == "Pune"
    assert payload["preferences"]["interests"] == ["sightseeing"]


def test_money_formats_negative_amounts():
    from frontend.presenters import money

    assert (
        money(-2940, "INR") == "−₹2,940" and money(25000, "USD") == "USD 25,000" and money(None, "INR") == "—"
    )


def test_markdown_from_llm_or_web_is_escaped():
    assert md_escape("[click](http://evil)") == r"\[click\]\(http://evil\)"


def test_presenter_rows(demo_response):
    entities = {e["id"]: e for e in demo_response["research"]["attractions"]}
    first = demo_response["itinerary"]["days"][0]["activities"][0]
    assert first["place_id"] in entities
    assert entities[first["place_id"]]["source_id"] in activity_line(first, entities, "INR")
    assert {r["Category"] for r in budget_rows(demo_response["budget"])} >= {"Accommodation", "Food"}
    assert all(r["URL"].startswith("https://demo.invalid/") for r in place_rows(demo_response))


# ---------- the Streamlit script itself ----------
def test_app_renders_form():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "AI Travel Planner"
    assert at.text_input[0].value == "Goa"


def test_app_shows_itinerary_after_submit(monkeypatch, demo_response):
    monkeypatch.setattr(api_client, "plan_trip", lambda base, payload, **kw: demo_response)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button[0].click().run()
    assert not at.exception
    assert "DEMO DATA" in at.warning[0].value
    assert any("Day 1" in s.value for s in at.subheader)
    assert [m.label for m in at.metric][:2] == ["Estimated total", "Your budget"]


def test_app_shows_api_error(monkeypatch):
    def fail(base, payload, **kw):
        raise api_client.PlannerAPIError(
            "CONFIGURATION_ERROR",
            "Not configured.",
            status=503,
            request_id="r9",
            details={"missing": ["GEMINI_API_KEY"]},
        )

    monkeypatch.setattr(api_client, "plan_trip", fail)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button[0].click().run()
    assert at.error[0].value == "Not configured."
    assert any("CONFIGURATION_ERROR" in c.value and "r9" in c.value for c in at.caption)
