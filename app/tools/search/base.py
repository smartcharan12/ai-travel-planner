"""The search abstraction: one interface, many possible providers.

The research workflow only ever talks to ``SearchProvider``. It never imports
Tavily or Serper directly. Swapping provider is a configuration change
(``SEARCH_PROVIDER=serper``), not a code change, and tests can plug in a fake.

Contract every provider must honour:

- input:  a ``ResearchQuery`` (category + exact query text) and ``max_results``
- output: ``list[SearchResultItem]``, possibly empty, in the provider's rank order
- errors: only our domain exceptions (``SearchTimeoutError``, ``SearchAuthError``,
          ``RateLimitError``, ``SearchProviderError``), never raw ``httpx`` errors,
          and never anything containing the API key
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.core.exceptions import (
    RateLimitError,
    SearchAuthError,
    SearchProviderError,
    SearchTimeoutError,
)
from app.schemas import ResearchQuery

logger = logging.getLogger(__name__)


class SearchResultItem(BaseModel):
    """A provider's result translated into neutral field names, before cleaning.

    Each provider names things differently (Tavily ``content``, Serper
    ``snippet``/``link``). This is the first normalization step. The second
    (ids, dedupe, filtering) happens in ``app/research/normalizer.py``.
    """

    title: str
    url: str
    content: str
    score: float | None = None


class SearchProvider(ABC):
    name: ClassVar[str]
    is_demo: ClassVar[bool] = False

    @abstractmethod
    async def search(self, query: ResearchQuery, *, max_results: int) -> list[SearchResultItem]:
        """Run one search and return provider-neutral results."""


class HttpSearchProvider(SearchProvider):
    """Shared HTTP plumbing and error mapping for JSON-over-HTTPS search APIs."""

    def __init__(self, *, timeout_seconds: float, transport: httpx.AsyncBaseTransport | None = None):
        self._timeout = timeout_seconds
        # Tests inject httpx.MockTransport here so no real network is used.
        self._transport = transport

    async def _post_json(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> Any:
        """POST and return parsed JSON, translating every failure into a domain error.

        Headers (which contain the API key) are never logged or attached to errors.
        """
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("search timeout provider=%s", self.name)
            raise SearchTimeoutError(details={"provider": self.name}) from exc
        except httpx.HTTPError as exc:
            logger.warning("search connection error provider=%s type=%s", self.name, type(exc).__name__)
            raise SearchProviderError(
                "Could not reach the travel search service.", details={"provider": self.name}
            ) from exc

        status = response.status_code
        if status in (401, 403):
            logger.error("search auth rejected provider=%s status=%s", self.name, status)
            raise SearchAuthError(details={"provider": self.name})
        if status == 429:
            raise RateLimitError(
                "The travel search service is rate-limiting us. Please try again shortly.",
                details={"provider": self.name, "upstream": True},
            )
        if status >= 400:
            logger.warning("search http error provider=%s status=%s", self.name, status)
            raise SearchProviderError(details={"provider": self.name, "upstream_status": status})

        try:
            return response.json()
        except ValueError as exc:
            raise SearchProviderError(details={"provider": self.name, "reason": "invalid_json"}) from exc
