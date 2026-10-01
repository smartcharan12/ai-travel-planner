"""Pick the search provider named in configuration.

This is the ONLY place that knows which concrete provider classes exist.
"""

from __future__ import annotations

from app.config import Settings
from app.core.exceptions import ConfigurationError
from app.tools.search.base import SearchProvider
from app.tools.search.demo import DemoSearchProvider
from app.tools.search.serper import SerperSearchProvider
from app.tools.search.tavily import TavilySearchProvider


def create_search_provider(settings: Settings) -> SearchProvider:
    """Build the configured provider, or fail loudly if its key is missing.

    There is deliberately no automatic fallback to demo data: silently
    swapping real research for invented samples would be a correctness bug
    disguised as resilience.
    """
    if settings.search_provider == "mock":
        return DemoSearchProvider()
    if settings.search_provider == "tavily":
        if settings.tavily_api_key is None:
            raise ConfigurationError(details={"missing": ["TAVILY_API_KEY"]})
        return TavilySearchProvider(
            settings.tavily_api_key,
            timeout_seconds=settings.search_timeout_seconds,
            search_depth=settings.tavily_search_depth,
        )
    if settings.search_provider == "serper":
        if settings.serper_api_key is None:
            raise ConfigurationError(details={"missing": ["SERPER_API_KEY"]})
        return SerperSearchProvider(settings.serper_api_key, timeout_seconds=settings.search_timeout_seconds)
    raise ConfigurationError(details={"unknown_search_provider": settings.search_provider})
