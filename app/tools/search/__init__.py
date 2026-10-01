"""Search providers behind one interface. Import the interface and factory from here."""

from app.tools.search.base import SearchProvider, SearchResultItem
from app.tools.search.factory import create_search_provider

__all__ = ["SearchProvider", "SearchResultItem", "create_search_provider"]
