"""The itinerary the LLM must produce, plus the budget our code computes.

Division of labour (a key design decision):

- The LLM decides WHAT to do and in which order (``Itinerary``). This is
  judgement: matching places to interests, pacing, grouping by area.
- Deterministic Python decides HOW MUCH it costs (``BudgetBreakdown``) and
  whether the plan breaks hard rules. LLMs are unreliable at arithmetic and
  must not be trusted to add up money.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from app.schemas.common import CostBasis, StrictModel

MAX_ACTIVITIES_PER_DAY = 6


class TimeSlot(StrEnum):
    """Coarse slots instead of exact clock times.

    The LLM has no reliable knowledge of today's opening hours or traffic, so
    asking it for '10:15–11:40' would produce confident fiction. Slots are
    honest about the precision we actually have.
    """

    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class ActivityType(StrEnum):
    SIGHTSEEING = "sightseeing"
    FOOD = "food"
    LEISURE = "leisure"
    NIGHTLIFE = "nightlife"
    SHOPPING = "shopping"
    TRANSIT = "transit"


class Activity(StrictModel):
    slot: TimeSlot
    activity_type: ActivityType
    title: str = Field(max_length=120)
    description: str = Field(max_length=600)
    place_id: str | None = Field(
        default=None,
        description=(
            "Id of an entity from ResearchResult (e.g. 'A2'). Null only for generic "
            "items like 'free time at the beach near your hotel'."
        ),
    )
    area: str | None = None
    estimated_cost: float | None = Field(
        default=None, ge=0, description="For the whole group, in the request currency."
    )
    cost_basis: CostBasis = CostBasis.UNKNOWN

    @model_validator(mode="after")
    def _cost_needs_basis(self) -> Activity:
        # A number with basis 'unknown' is a contradiction: either the model
        # knows where the price came from, or it must not state one.
        if self.estimated_cost is not None and self.cost_basis == CostBasis.UNKNOWN:
            raise ValueError("estimated_cost given but cost_basis is 'unknown'")
        return self


class DailyPlan(StrictModel):
    day_number: int = Field(ge=1)
    calendar_date: date | None = None
    theme: str = Field(max_length=120, examples=["North Goa beaches and sunset"])
    activities: list[Activity] = Field(min_length=1, max_length=MAX_ACTIVITIES_PER_DAY)


class AccommodationChoice(StrictModel):
    hotel_id: str | None = Field(default=None, description="Id of a Hotel from research, if any.")
    name: str
    area: str | None = None
    nightly_rate: float | None = Field(default=None, ge=0, description="Per room per night.")
    cost_basis: CostBasis = CostBasis.UNKNOWN
    rooms: int = Field(default=1, ge=1, le=10)


class Itinerary(StrictModel):
    """Structured output contract for the itinerary-generation LLM call."""

    title: str = Field(max_length=150)
    summary: str = Field(max_length=1000)
    accommodation: AccommodationChoice | None = None
    days: list[DailyPlan] = Field(min_length=1)
    recommendations: list[str] = Field(default_factory=list, max_length=10)
    travel_tips: list[str] = Field(default_factory=list, max_length=10)
    uncertainty_notes: list[str] = Field(
        default_factory=list,
        description="Things the model could not verify, stated explicitly instead of guessed.",
    )


class BudgetBreakdown(StrictModel):
    """Computed by deterministic code (Stage 2), never by the LLM."""

    currency: str
    accommodation: float = Field(ge=0)
    food: float = Field(ge=0)
    local_transport: float = Field(ge=0)
    intercity_transport: float = Field(ge=0)
    activities: float = Field(ge=0)
    miscellaneous: float = Field(ge=0)
    total: float = Field(ge=0)
    budget: float = Field(gt=0)
    remaining: float = Field(description="budget - total; negative means over budget.")
    within_budget: bool
    per_person_total: float = Field(ge=0)
    assumptions: list[str] = Field(
        default_factory=list,
        description="Every heuristic used, e.g. 'food: ₹900/person/day (mid_range default)'.",
    )
