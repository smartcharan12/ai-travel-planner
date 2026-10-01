"""Shapes for what the research step produces.

Data moves through three levels of trust:

1. ``SearchHit``       normalized result from Tavily/Serper: untrusted web text,
                       but with a stable id (``S3``), URL, domain, category and
                       the exact query that found it.
2. typed entities      ``Attraction``, ``Restaurant``, ... extracted by the LLM.
                       Each one MUST cite ``source_id`` (the SearchHit it came
                       from), and ``app/research/grounding.py`` drops any entity
                       whose name does not appear in that source's text.
3. ``ResearchResult``  the verified bundle. Later stages may only schedule
                       places listed here, by id.

Traceability chain:  entity.source_id  ->  SearchHit.source_id  ->  SearchHit.url
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.schemas.common import PriceInfo, Source, StrictModel


class ResearchCategory(StrEnum):
    """The fixed research plan. Every request searches all five, in this order."""

    DESTINATION = "destination"
    ATTRACTIONS = "attractions"
    RESTAURANTS = "restaurants"
    HOTELS = "hotels"
    TRANSPORTATION = "transportation"


class ResearchQuery(StrictModel):
    """One deterministic search built from the request (``app/research/queries.py``)."""

    category: ResearchCategory
    destination: str
    text: str = Field(description="The exact query string sent to the search provider.")


class SearchHit(StrictModel):
    """One normalized search result, identical in shape whichever provider ran."""

    source_id: str = Field(description="Stable id within this request: S1, S2, ...")
    category: ResearchCategory
    query: str = Field(description="The query that produced this result.")
    title: str
    url: str
    domain: str = Field(examples=["goa-tourism.com"])
    content: str = Field(description="Cleaned snippet text. Untrusted: may contain anything.")
    score: float | None = Field(default=None, description="Provider relevance score, if given.")
    provider: str
    retrieved_at: datetime

    def to_source(self) -> Source:
        return Source(
            id=self.source_id,
            title=self.title,
            url=self.url,
            provider=self.provider,
            retrieved_at=self.retrieved_at,
        )


class CategorySearchSummary(StrictModel):
    """What happened to one research category, shown in the response for transparency."""

    category: ResearchCategory
    query: str
    status: Literal["ok", "empty", "failed"]
    raw_results: int = Field(ge=0, description="Results returned by the provider.")
    kept_results: int = Field(ge=0, description="Results left after normalization/filtering.")
    latency_ms: float | None = None
    error_code: str | None = None


class _Entity(StrictModel):
    id: str = Field(description="Stable id later stages refer to, e.g. 'A2', 'R1', 'H1', 'T1'.")
    name: str
    area: str | None = Field(default=None, description="Neighbourhood/region, used to cluster days.")
    source_id: str = Field(description="Which SearchHit this entity was extracted from.")


class Attraction(_Entity):
    description: str
    category: str | None = Field(default=None, examples=["beach", "fort", "museum"])
    typical_duration_hours: float | None = Field(default=None, gt=0, le=12)
    price: PriceInfo | None = Field(default=None, description="Entry fee, only if stated by the source.")


class Restaurant(_Entity):
    description: str | None = None
    cuisine: str | None = None
    dietary_notes: str | None = None
    price: PriceInfo | None = None


class Hotel(_Entity):
    description: str | None = None
    accommodation_type: str | None = None
    price: PriceInfo | None = None


class Transportation(_Entity):
    mode: str = Field(examples=["flight", "train", "scooter rental", "taxi"])
    scope: Literal["intercity", "local"]
    description: str | None = None
    duration_note: str | None = None
    price: PriceInfo | None = None


class DestinationInfo(StrictModel):
    name: str
    summary: str
    best_time_to_visit: str | None = None
    local_tips: list[str] = Field(default_factory=list, max_length=10)
    source_ids: list[str] = Field(default_factory=list)


class ResearchResult(StrictModel):
    """Everything later stages are allowed to know about the trip."""

    destination_info: DestinationInfo | None = None
    attractions: list[Attraction] = Field(default_factory=list)
    restaurants: list[Restaurant] = Field(default_factory=list)
    hotels: list[Hotel] = Field(default_factory=list)
    transportation: list[Transportation] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description="Partial failures, e.g. 'hotel search failed'. Surfaced to the user.",
    )
    uncertainty_notes: list[str] = Field(
        default_factory=list, description="What the model said it could not verify from the sources."
    )
    searched_at: datetime

    def entity_ids(self) -> set[str]:
        """All ids an itinerary activity may legally reference."""
        return set(self.entity_index())

    def entity_index(self) -> dict[str, Attraction | Restaurant | Hotel | Transportation]:
        """Look up any verified entity by id ('A1', 'R2', ...)."""
        groups = (self.attractions, self.restaurants, self.hotels, self.transportation)
        return {entity.id: entity for group in groups for entity in group}


class RejectedEntity(StrictModel):
    """An LLM-extracted item that failed a grounding check and was discarded."""

    entity_type: Literal["attraction", "restaurant", "hotel", "transportation", "destination_info"]
    name: str
    source_id: str | None
    reason: Literal["UNKNOWN_SOURCE_ID", "NAME_NOT_IN_SOURCE", "DUPLICATE", "OVER_LIMIT", "NO_VALID_SOURCES"]


class RemovedPrice(StrictModel):
    """A price the LLM reported that could not be matched to its source text."""

    entity_id: str
    quote: str
    reason: Literal["QUOTE_NOT_IN_SOURCE", "AMOUNT_NOT_IN_QUOTE"]


class GroundingReport(StrictModel):
    """Result of the deterministic checks applied to the LLM's extraction."""

    extracted: int = Field(ge=0, description="Entities the LLM returned.")
    accepted: int = Field(ge=0, description="Entities that passed every check.")
    rejected: list[RejectedEntity] = Field(default_factory=list)
    prices_removed: list[RemovedPrice] = Field(default_factory=list)
