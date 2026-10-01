"""POST /api/v1/research (the Stage 2 behaviour): success shape and error mapping through HTTP."""

from __future__ import annotations

import json

import pytest

from app.api.dependencies import get_research_planner
from app.config import get_settings
from app.core.exceptions import RateLimitError, SearchAuthError, SearchTimeoutError
from app.llm.client import StructuredLLM
from app.schemas import ResearchCategory
from app.services.research_planner import ResearchPlanner
from tests.fakes import FakeSearchProvider, ScriptedChatModel, goa_extraction_json, goa_items


def _override(client, make_settings, search, script):
    llm = StructuredLLM(
        ScriptedChatModel(script=script),
        model_name="gemini-test",
        timeout_seconds=5,
        output_retries=1,
        native_json_schema=False,
    )
    client.app.dependency_overrides[get_research_planner] = lambda: ResearchPlanner(
        make_settings(), search_provider=search, llm=llm
    )


def test_live_shaped_success_response(client, make_settings, goa_payload):
    _override(client, make_settings, FakeSearchProvider(goa_items()), [json.dumps(goa_extraction_json())])
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data_mode"] == "live" and "verify prices" in body["notice"]
    assert body["next_step"].startswith("This endpoint returns verified research only")
    assert {s["category"] for s in body["search_summary"]} == {c.value for c in ResearchCategory}
    assert body["research"]["attractions"][0]["source_id"] == "S2"


def test_missing_keys_return_503_with_names_only(client, make_settings, goa_payload):
    client.app.dependency_overrides[get_settings] = lambda: make_settings(tavily_api_key="tvly-REAL-SECRET")
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == 503
    error = resp.json()["error"]
    assert error["code"] == "CONFIGURATION_ERROR"
    assert error["details"] == {"missing": ["GEMINI_API_KEY"]}
    assert "tvly-REAL-SECRET" not in resp.text


def test_invalid_body_is_still_422_when_keys_are_missing(client, make_settings, goa_payload):
    client.app.dependency_overrides[get_settings] = lambda: make_settings()
    goa_payload["num_days"] = 0
    assert client.post("/api/v1/research", json=goa_payload).status_code == 422


@pytest.mark.parametrize(
    "exc,status,code",
    [
        (SearchTimeoutError(), 504, "SEARCH_TIMEOUT"),
        (SearchAuthError(), 502, "SEARCH_PROVIDER_AUTH_ERROR"),
        (RateLimitError(), 429, "RATE_LIMITED"),
    ],
)
def test_search_failures_map_to_status_codes(client, make_settings, goa_payload, exc, status, code):
    _override(client, make_settings, FakeSearchProvider({c: exc for c in ResearchCategory}), [])
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == status and resp.json()["error"]["code"] == code


def test_no_results_is_422(client, make_settings, goa_payload):
    _override(client, make_settings, FakeSearchProvider({}), [])
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "NO_RESEARCH_RESULTS"


def test_malformed_llm_output_is_502(client, make_settings, goa_payload):
    _override(client, make_settings, FakeSearchProvider(goa_items()), ["nope", "still nope"])
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "LLM_INVALID_OUTPUT"


def test_llm_timeout_is_504(client, make_settings, goa_payload):
    from langchain_core.exceptions import ModelTimeoutError

    _override(client, make_settings, FakeSearchProvider(goa_items()), [ModelTimeoutError("slow")])
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == 504 and resp.json()["error"]["code"] == "LLM_TIMEOUT"


def test_openapi_documents_research_response(client):
    spec = client.get("/openapi.json").json()
    plan = spec["paths"]["/api/v1/research"]["post"]
    assert plan["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "ResearchResponse"
    )
    assert "503" in plan["responses"]
