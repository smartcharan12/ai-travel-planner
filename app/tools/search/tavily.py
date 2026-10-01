"""Tavily search provider (https://docs.tavily.com).

Why Tavily as the default: it is built for LLM applications. Its ``content``
field is a relevant extract of the page rather than a 2-line Google snippet,
which gives the extraction step more evidence per result.

Raw response shape (fields we use):
    {"query": "...", "results": [{"title": "...", "url": "...", "content": "...", "score": 0.83}, ...]}
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.core.exceptions import SearchProviderError
from app.schemas import ResearchQuery
from app.tools.search.base import HttpSearchProvider, SearchResultItem

TAVILY_URL = "https://api.tavily.com/search"


class TavilySearchProvider(HttpSearchProvider):
    name = "tavily"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        timeout_seconds: float,
        search_depth: str = "basic",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(timeout_seconds=timeout_seconds, transport=transport)
        self._api_key = api_key
        self._search_depth = search_depth

    async def search(self, query: ResearchQuery, *, max_results: int) -> list[SearchResultItem]:
        payload = {
            "query": query.text,
            "max_results": max_results,
            "search_depth": self._search_depth,  # "basic" = 1 credit, "advanced" = 2
            "topic": "general",
            "include_answer": False,  # we want sources, not Tavily's own LLM summary
            "include_raw_content": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        data = await self._post_json(TAVILY_URL, headers=headers, payload=payload)
        return parse_tavily_response(data)


def parse_tavily_response(data: Any) -> list[SearchResultItem]:
    """Translate Tavily JSON to ``SearchResultItem``s, skipping malformed entries.

    A missing ``results`` key means the API contract changed or we got an
    error page, so that is an error. An empty list is a valid "found nothing".
    """
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SearchProviderError(details={"provider": "tavily", "reason": "unexpected_response_shape"})
    items: list[SearchResultItem] = []
    for raw in data["results"]:
        if not isinstance(raw, dict) or not raw.get("url"):
            continue
        items.append(
            SearchResultItem(
                title=str(raw.get("title") or ""),
                url=str(raw["url"]),
                content=str(raw.get("content") or ""),
                score=raw.get("score") if isinstance(raw.get("score"), int | float) else None,
            )
        )
    return items
