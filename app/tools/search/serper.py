"""Serper provider (https://serper.dev): Google results as JSON.

Present to prove the abstraction works: switching provider is only
``SEARCH_PROVIDER=serper`` plus ``SERPER_API_KEY``. Serper snippets are
shorter than Tavily extracts, so expect fewer extracted entities.

Raw response shape (fields we use):
    {"organic": [{"title": "...", "link": "...", "snippet": "...", "position": 1}, ...]}
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.core.exceptions import SearchProviderError
from app.schemas import ResearchQuery
from app.tools.search.base import HttpSearchProvider, SearchResultItem

SERPER_URL = "https://google.serper.dev/search"


class SerperSearchProvider(HttpSearchProvider):
    name = "serper"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(timeout_seconds=timeout_seconds, transport=transport)
        self._api_key = api_key

    async def search(self, query: ResearchQuery, *, max_results: int) -> list[SearchResultItem]:
        headers = {"X-API-KEY": self._api_key.get_secret_value()}
        data = await self._post_json(
            SERPER_URL, headers=headers, payload={"q": query.text, "num": max_results}
        )
        return parse_serper_response(data)[:max_results]


def parse_serper_response(data: Any) -> list[SearchResultItem]:
    if not isinstance(data, dict):
        raise SearchProviderError(details={"provider": "serper", "reason": "unexpected_response_shape"})
    organic = data.get("organic", [])
    if not isinstance(organic, list):
        raise SearchProviderError(details={"provider": "serper", "reason": "unexpected_response_shape"})
    items: list[SearchResultItem] = []
    for raw in organic:
        if not isinstance(raw, dict) or not raw.get("link"):
            continue
        items.append(
            SearchResultItem(
                title=str(raw.get("title") or ""),
                url=str(raw["link"]),
                content=str(raw.get("snippet") or ""),
                score=None,  # Serper gives a rank position, not a relevance score
            )
        )
    return items
