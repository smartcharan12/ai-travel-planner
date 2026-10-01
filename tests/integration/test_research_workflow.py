"""The real LangGraph workflow end to end, with fake search and fake LLM.

"Integration" here = many of our own components working together (queries ->
search -> normalization -> prompt -> LLM client -> grounding -> response).
External services are still faked; tests needing real keys live in tests/live/.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import (
    LLMOutputError,
    NoResearchResultsError,
    SearchAuthError,
    SearchProviderError,
    SearchTimeoutError,
)
from app.llm.client import StructuredLLM
from app.schemas import ResearchCategory, TravelRequest
from app.services.research_planner import ResearchPlanner
from app.tools.search.tavily import TavilySearchProvider
from tests.fakes import FakeSearchProvider, ScriptedChatModel, goa_extraction_json, goa_items

C = ResearchCategory


def _llm(script) -> StructuredLLM:
    model = ScriptedChatModel(
        script=script, usage={"input_tokens": 2000, "output_tokens": 500, "total_tokens": 2500}
    )
    return StructuredLLM(
        model, model_name="gemini-test", timeout_seconds=5, output_retries=1, native_json_schema=False
    )


def _run(make_settings, goa_payload, search, llm):
    planner = ResearchPlanner(make_settings(), search_provider=search, llm=llm)
    return asyncio.run(planner.run(TravelRequest.model_validate(goa_payload), request_id="req-1"))


def test_full_goa_research_is_typed_traceable_and_filtered(make_settings, goa_payload):
    search = FakeSearchProvider(goa_items())
    resp = _run(make_settings, goa_payload, search, _llm([json.dumps(goa_extraction_json())]))

    # fixed workflow: exactly one query per category
    assert sorted(q.category for q in search.queries) == sorted(ResearchCategory)
    assert resp.status == "success" and resp.data_mode == "live" and resp.stage == "research"
    assert [h.source_id for h in resp.search_results] == ["S1", "S2", "S3", "S4", "S5"]

    # traceability: every entity -> a returned search result -> its URL
    hits = {h.source_id: h for h in resp.search_results}
    for group in (
        resp.research.attractions,
        resp.research.restaurants,
        resp.research.hotels,
        resp.research.transportation,
    ):
        for entity in group:
            assert entity.source_id in hits
            assert entity.name.lower() in hits[entity.source_id].content.lower()

    # hallucination controls visible in the response
    assert [r.name for r in resp.grounding.rejected] == ["Dudhsagar Falls"]
    assert resp.research.hotels[0].price is None
    assert any("discarded" in w for w in resp.warnings)

    # observability metadata
    assert resp.metadata.llm_calls == 1
    assert (resp.metadata.input_tokens, resp.metadata.output_tokens) == (2000, 500)
    assert resp.metadata.search_provider == "fake-search" and resp.metadata.is_demo is False


def test_one_failed_category_gives_partial_result(make_settings, goa_payload):
    items = goa_items()
    items[C.HOTELS] = SearchTimeoutError()
    data = goa_extraction_json()
    data["hotels"] = []
    # hotels missing -> ids shift: transport source becomes S4
    for t in data["transportation"]:
        t["source_id"] = "S4"
    resp = _run(make_settings, goa_payload, FakeSearchProvider(items), _llm([json.dumps(data)]))
    assert resp.status == "partial"
    hotel_summary = next(s for s in resp.search_summary if s.category == C.HOTELS)
    assert (hotel_summary.status, hotel_summary.error_code) == ("failed", "SEARCH_TIMEOUT")
    assert any("hotels search failed" in w for w in resp.warnings)
    assert resp.research.transportation


@pytest.mark.parametrize("exc", [SearchTimeoutError(), SearchAuthError()])
def test_all_categories_failing_surfaces_the_real_cause(make_settings, goa_payload, exc):
    search = FakeSearchProvider({c: exc for c in ResearchCategory})
    with pytest.raises(type(exc)):
        _run(make_settings, goa_payload, search, _llm([]))


def test_empty_search_results_stop_before_the_llm(make_settings, goa_payload):
    llm = _llm([])  # would raise IndexError if called
    with pytest.raises(NoResearchResultsError):
        _run(make_settings, goa_payload, FakeSearchProvider({}), llm)


def test_unexpected_provider_bug_is_contained_per_category(make_settings, goa_payload):
    items = goa_items()
    items[C.DESTINATION] = KeyError("provider bug")
    data = goa_extraction_json()
    data["destination_info"] = None
    for group in ("attractions", "restaurants", "hotels", "transportation"):
        for e in data[group]:
            e["source_id"] = f"S{int(e['source_id'][1:]) - 1}"
    resp = _run(make_settings, goa_payload, FakeSearchProvider(items), _llm([json.dumps(data)]))
    summary = next(s for s in resp.search_summary if s.category == C.DESTINATION)
    assert summary.error_code == SearchProviderError.code


def test_malformed_llm_output_twice_fails_cleanly(make_settings, goa_payload):
    with pytest.raises(LLMOutputError):
        _run(make_settings, goa_payload, FakeSearchProvider(goa_items()), _llm(["{bad", "{still bad"]))


def test_workflow_with_tavily_over_mocked_http(make_settings, goa_payload):
    """Real TavilySearchProvider + normalization, with HTTP answered by a fake server."""
    by_keyword = {
        "travel guide": goa_items()[C.DESTINATION],
        "things to do": goa_items()[C.ATTRACTIONS],
        "restaurants": goa_items()[C.RESTAURANTS],
        "hotels": goa_items()[C.HOTELS],
        "travel from": goa_items()[C.TRANSPORTATION],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        items = next(v for k, v in by_keyword.items() if k in query)
        return httpx.Response(200, json={"results": [i.model_dump() for i in items]})

    tavily = TavilySearchProvider(SecretStr("k"), timeout_seconds=5, transport=httpx.MockTransport(handler))
    resp = _run(make_settings, goa_payload, tavily, _llm([json.dumps(goa_extraction_json())]))
    assert resp.metadata.search_provider == "tavily"
    assert [h.domain for h in resp.search_results][:2] == ["guide.example.com", "example-travel.com"]
    assert len(resp.research.attractions) == 2
