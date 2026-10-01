"""Offline demo search provider. Selected only by explicit configuration."""

from __future__ import annotations

from app.demo.data import demo_results
from app.schemas import ResearchQuery
from app.tools.search.base import SearchProvider, SearchResultItem


class DemoSearchProvider(SearchProvider):
    """Returns invented, clearly labelled sample results; makes no network calls."""

    name = "demo"
    is_demo = True

    async def search(self, query: ResearchQuery, *, max_results: int) -> list[SearchResultItem]:
        rows = demo_results(query.destination, query.category)[:max_results]
        return [SearchResultItem(title=r["title"], url=r["url"], content=r["content"]) for r in rows]
