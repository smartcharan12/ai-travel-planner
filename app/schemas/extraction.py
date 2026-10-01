"""The structured-output contract for the research-extraction LLM call.

These models are what Gemini must return. They are deliberately *different*
from the final ``ResearchResult`` models:

- no ``id`` fields: our code assigns ids (A1, R1, ...) after verification, so
  the model cannot create duplicate or misleading ids;
- no ``basis`` on prices: the model may only quote a price it saw. Whether
  that quote is trusted is decided by ``app/research/grounding.py``;
- every entity must name a ``source_id`` from the numbered sources it was shown.

The JSON Schema generated from these classes is also sent to Gemini
(``response_json_schema``) so the model is constrained while generating, and
Pydantic re-validates the reply afterwards, because constraints are not a
guarantee.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel


class ExtractedPrice(StrictModel):
    quote: str = Field(max_length=200, description="Copy the price text exactly as written in the source.")
    amount: float | None = Field(default=None, ge=0, description="The number in the quote, without commas.")
    currency: str | None = Field(default=None, description="ISO code such as INR, USD, EUR.")
    unit: str | None = Field(default=None, description="e.g. 'per night', 'for two', 'per person'.")


class _ExtractedEntity(StrictModel):
    name: str = Field(max_length=120, description="Exactly as written in the source.")
    source_id: str = Field(description="Id of the source this came from, e.g. 'S3'.")
    area: str | None = Field(default=None, max_length=80)


class ExtractedAttraction(_ExtractedEntity):
    description: str = Field(max_length=400)
    category: str | None = Field(default=None, max_length=40)
    typical_duration_hours: float | None = Field(default=None, gt=0, le=12)
    price: ExtractedPrice | None = None


class ExtractedRestaurant(_ExtractedEntity):
    description: str | None = Field(default=None, max_length=400)
    cuisine: str | None = Field(default=None, max_length=80)
    dietary_notes: str | None = Field(default=None, max_length=200)
    price: ExtractedPrice | None = None


class ExtractedHotel(_ExtractedEntity):
    description: str | None = Field(default=None, max_length=400)
    accommodation_type: str | None = Field(default=None, max_length=40)
    price: ExtractedPrice | None = None


class ExtractedTransportation(_ExtractedEntity):
    mode: str = Field(max_length=40)
    scope: Literal["intercity", "local"]
    description: str | None = Field(default=None, max_length=400)
    duration_note: str | None = Field(default=None, max_length=120)
    price: ExtractedPrice | None = None


class ExtractedDestinationInfo(StrictModel):
    summary: str = Field(max_length=800)
    best_time_to_visit: str | None = Field(default=None, max_length=200)
    local_tips: list[str] = Field(default_factory=list, max_length=8)
    source_ids: list[str] = Field(description="Sources that support the summary and tips.")


class ResearchExtraction(StrictModel):
    """Top-level object Gemini must return for the extraction step."""

    destination_info: ExtractedDestinationInfo | None = None
    attractions: list[ExtractedAttraction] = Field(default_factory=list)
    restaurants: list[ExtractedRestaurant] = Field(default_factory=list)
    hotels: list[ExtractedHotel] = Field(default_factory=list)
    transportation: list[ExtractedTransportation] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Anything relevant you could NOT find or verify in the sources.",
    )
