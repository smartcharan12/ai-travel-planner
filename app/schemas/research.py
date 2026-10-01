"""Shapes for what the research step produces.

Data moves through three levels of trust:

1. ``SearchHit``       raw result from Tavily/Serper: untrusted web text
2. typed entities      ``Attraction``, ``Restaurant``, ... pulled out of the hits.
                       Each one MUST cite the ``source_id`` it came from, and
                       the workflow drops any entity whose name does not appear
                       in that source's text (Stage 2).
3. ``ResearchResult``  the bundle the itinerary LLM is allowed to use. The
                       planner may only schedule places listed here, by id.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from app.schemas.common import Source, StrictModel


class ResearchCategory(StrEnum):
    DESTINATION = "destination"
    ATTRACTIONS = "attractions"
    RESTAURANTS = "restaurants"
    HOTELS = "hotels"
    TRANSPORTATION = "transportation"


class SearchHit(StrictModel):
    """One normalized result from any search provider (provider-neutral)."""

    source_id: str
    category: ResearchCategory
    title: str
    url: str
    content: str = Field(description="Snippet/extract text. Untrusted: may contain anything.")
    score: float | None = Field(default=None, description="Provider relevance score, if given.")


class _Entity(StrictModel):
    id: str = Field(description="Stable id the itinerary refers to, e.g. 'A2', 'R1', 'H1'.")
    name: str
    area: str | None = Field(default=None, description="Neighbourhood/region, used to cluster days.")
    source_id: str = Field(description="Which SearchHit this entity was extracted from.")


class Attraction(_Entity):
    description: str
    category: str | None = Field(default=None, examples=["beach", "fort", "museum"])
    typical_duration_hours: float | None = Field(default=None, gt=0, le=12)
    entry_fee_note: str | None = Field(
        default=None, description="Copied from the source if stated; never invented."
    )


class Restaurant(_Entity):
    cuisine: str | None = None
    price_note: str | None = Field(default=None, description="As stated by the source, e.g. '₹800 for two'.")
    dietary_notes: str | None = None


class Hotel(_Entity):
    accommodation_type: str | None = None
    price_note: str | None = None


class Transportation(_Entity):
    mode: str = Field(examples=["flight", "train", "scooter rental", "taxi"])
    scope: str = Field(examples=["intercity", "local"])
    price_note: str | None = None
    duration_note: str | None = None


class DestinationInfo(StrictModel):
    name: str
    summary: str
    best_time_to_visit: str | None = None
    local_tips: list[str] = Field(default_factory=list, max_length=10)
    source_ids: list[str] = Field(default_factory=list)


class ResearchResult(StrictModel):
    """Everything the itinerary generator is allowed to know about the trip."""

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
    searched_at: datetime

    def entity_ids(self) -> set[str]:
        """All ids an itinerary activity may legally reference."""
        groups = (self.attractions, self.restaurants, self.hotels, self.transportation)
        return {entity.id for group in groups for entity in group}
