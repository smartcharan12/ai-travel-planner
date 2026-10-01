"""Small building blocks reused by request, research and itinerary schemas."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class StrictModel(BaseModel):
    """Base for every schema: unknown fields are rejected, not silently dropped.

    Rejecting extras matters doubly for LLM output: if the model invents a
    field we did not ask for, we want to know rather than ignore it.
    """

    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class CostBasis(StrEnum):
    """Where a money figure came from. Shown to the user next to every price.

    This is a core anti-hallucination device: a number is never presented
    without saying how trustworthy it is.
    """

    SOURCE = "source"  # quoted from a cited search result
    ESTIMATE = "estimate"  # developer default from app/planning/budget_rates.py, or an assumed unit
    UNKNOWN = "unknown"  # no reliable figure; user must check


class Source(StrictModel):
    """A web page the plan relies on. Every factual claim should trace to one."""

    id: str = Field(description="Short stable id, e.g. 'S3', used for citations in prompts.")
    title: str
    url: str
    provider: str = Field(description="Which search API returned it, e.g. 'tavily'.")
    retrieved_at: datetime

    @field_validator("url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        # Blocks javascript:, file:, data: URLs that a malicious page could inject.
        if not value.startswith(("http://", "https://")):
            raise ValueError("source url must be http(s)")
        return value


class PriceInfo(StrictModel):
    """A price for a researched entity, kept together with its evidence.

    ``quote`` is the exact text from the source (e.g. "₹2,500 per night") so a
    human can check the number. Research prices are only ever ``source``:
    the LLM is never allowed to estimate. A price that cannot be matched to its
    source text is removed (``app/research/grounding.py``), not guessed.
    """

    amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    unit: str | None = Field(default=None, max_length=60, examples=["per night", "for two", "per person"])
    quote: str = Field(max_length=200, description="Verbatim text from the cited source.")
    basis: CostBasis = CostBasis.SOURCE
