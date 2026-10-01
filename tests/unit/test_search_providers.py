"""Search providers: HTTP is mocked with httpx.MockTransport (no network)."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.exceptions import (
    ConfigurationError,
    RateLimitError,
    SearchAuthError,
    SearchProviderError,
    SearchTimeoutError,
)
from app.tools.search import create_search_provider
from app.tools.search.demo import DemoSearchProvider
from app.tools.search.serper import SerperSearchProvider
from app.tools.search.tavily import TavilySearchProvider
from tests.fakes import TAVILY_GOA_ATTRACTIONS, make_query

KEY = "tvly-SECRET-test-key"


def _tavily(handler) -> TavilySearchProvider:
    return TavilySearchProvider(SecretStr(KEY), timeout_seconds=5, transport=httpx.MockTransport(handler))


def _run(provider, **kwargs):
    return asyncio.run(provider.search(make_query(), max_results=5, **kwargs))


def test_tavily_sends_query_and_bearer_key_and_parses_results():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=TAVILY_GOA_ATTRACTIONS)

    items = _run(_tavily(handler))
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["query"] == "attractions in Goa"
    assert seen["body"]["include_answer"] is False
    assert [i.title for i in items] == ["15 Best Things to Do in Goa", "Goa beaches guide"]
    assert items[0].url.startswith("https://www.example-travel.com/goa")
    assert items[0].score == 0.91


def test_tavily_empty_results_is_valid():
    assert _run(_tavily(lambda r: httpx.Response(200, json={"query": "q", "results": []}))) == []


def test_tavily_skips_malformed_entries():
    payload = {"results": [{"title": "no url"}, "junk", {"url": "https://ok.example", "content": "x"}]}
    items = _run(_tavily(lambda r: httpx.Response(200, json=payload)))
    assert [i.url for i in items] == ["https://ok.example"]


@pytest.mark.parametrize(
    "status,exc_type",
    [
        (401, SearchAuthError),
        (403, SearchAuthError),
        (429, RateLimitError),
        (500, SearchProviderError),
        (503, SearchProviderError),
    ],
)
def test_tavily_http_errors_map_to_domain_errors(status, exc_type):
    with pytest.raises(exc_type) as info:
        _run(_tavily(lambda r: httpx.Response(status, json={"detail": f"bad key {KEY}"})))
    assert KEY not in str(info.value) and KEY not in str(info.value.details)


def test_tavily_timeout():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(SearchTimeoutError):
        _run(_tavily(handler))


def test_tavily_connection_error():
    def handler(request):
        raise httpx.ConnectError("dns failure", request=request)

    with pytest.raises(SearchProviderError) as info:
        _run(_tavily(handler))
    assert info.value.code == "SEARCH_PROVIDER_ERROR"


@pytest.mark.parametrize("body", ["<html>error page</html>", json.dumps({"unexpected": True})])
def test_tavily_invalid_or_unexpected_body(body):
    with pytest.raises(SearchProviderError):
        _run(_tavily(lambda r: httpx.Response(200, content=body)))


def test_serper_parses_organic_results_with_its_own_key_header():
    seen = {}

    def handler(request):
        seen["key"] = request.headers["X-API-KEY"]
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Baga Beach",
                        "link": "https://example.com/baga",
                        "snippet": "Baga Beach, Goa",
                        "position": 1,
                    }
                ]
            },
        )

    provider = SerperSearchProvider(
        SecretStr("serper-k"), timeout_seconds=5, transport=httpx.MockTransport(handler)
    )
    items = _run(provider)
    assert seen["key"] == "serper-k"
    assert items[0].url == "https://example.com/baga" and items[0].content == "Baga Beach, Goa"


def test_demo_provider_is_labelled_and_offline():
    items = _run(DemoSearchProvider())
    assert DemoSearchProvider.is_demo
    assert items and all(i.url.startswith("https://demo.invalid/") for i in items)
    assert all("(DEMO)" in i.title and "[DEMO DATA, not real]" in i.content for i in items)


def test_factory_selects_configured_provider(make_settings):
    assert isinstance(create_search_provider(make_settings(demo_mode=True)), DemoSearchProvider)
    tavily = create_search_provider(make_settings(tavily_api_key="k"))
    assert isinstance(tavily, TavilySearchProvider)
    serper = create_search_provider(make_settings(search_provider="serper", serper_api_key="k"))
    assert isinstance(serper, SerperSearchProvider)


def test_factory_refuses_missing_key_instead_of_falling_back_to_demo(make_settings):
    with pytest.raises(ConfigurationError) as info:
        create_search_provider(make_settings())
    assert info.value.details == {"missing": ["TAVILY_API_KEY"]}
