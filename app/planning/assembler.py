"""Turn a validated ``ItineraryDraft`` into the final ``Itinerary``.

The LLM chose *what* and *when*. Code adds the facts:

- ``title`` from the verified place name or the generic kind (never LLM text)
- ``calendar_date`` from ``start_date`` + day offset (if dates were given)
- ``area`` from the verified entity, not from the model's text
- ``estimated_cost`` only from a verified source price (``basis: source``);
  if the source did not state the unit (per person? per group?) the cost is
  still computed but labelled ``basis: estimate``; with no price at all it is
  ``None`` with ``basis: unknown``. Never a guess.
- the accommodation choice from the verified hotel, with its verified rate
"""

from __future__ import annotations

from datetime import timedelta

from app.planning.pricing import GroupCost, price_for_group
from app.planning.rules import rooms_needed
from app.planning.titles import activity_title
from app.schemas import (
    AccommodationChoice,
    Activity,
    CostBasis,
    DailyPlan,
    Itinerary,
    ItineraryDraft,
    ResearchResult,
    TravelRequest,
)


def _accommodation(draft: ItineraryDraft, research: ResearchResult, request: TravelRequest):
    hotel = next((h for h in research.hotels if h.id == draft.hotel_id), None)
    if hotel is None:
        return None
    rate = None
    if (
        hotel.price
        and hotel.price.amount is not None
        and "night" in f"{hotel.price.unit} {hotel.price.quote}".lower()
    ):
        rate = hotel.price.amount
    return AccommodationChoice(
        hotel_id=hotel.id,
        name=hotel.name,
        area=hotel.area,
        nightly_rate=rate,
        cost_basis=CostBasis.SOURCE if rate is not None else CostBasis.UNKNOWN,
        rooms=rooms_needed(request.num_travelers),
    )


def _basis(cost: GroupCost | None) -> CostBasis:
    if cost is None:
        return CostBasis.UNKNOWN
    return CostBasis.ESTIMATE if cost.assumed_unit else CostBasis.SOURCE


def assemble_itinerary(draft: ItineraryDraft, research: ResearchResult, request: TravelRequest) -> Itinerary:
    entities = research.entity_index()
    days = []
    for day in sorted(draft.days, key=lambda d: d.day_number):
        activities = []
        for a in day.activities:
            entity = entities.get(a.place_id) if a.place_id else None
            cost = price_for_group(getattr(entity, "price", None), request.num_travelers, request.currency)
            activities.append(
                Activity(
                    slot=a.slot,
                    activity_type=a.activity_type,
                    title=activity_title(
                        slot=a.slot,
                        activity_type=a.activity_type,
                        place_name=entity.name if entity else None,
                        generic_kind=a.generic_kind,
                        destination=request.destination,
                    ),
                    generic_kind=a.generic_kind,
                    description=a.description,
                    place_id=a.place_id,
                    area=entity.area if entity else None,
                    estimated_cost=round(cost.amount, 2) if cost else None,
                    cost_basis=_basis(cost),
                )
            )
        calendar_date = (
            request.start_date + timedelta(days=day.day_number - 1) if request.start_date else None
        )
        days.append(
            DailyPlan(
                day_number=day.day_number, calendar_date=calendar_date, theme=day.theme, activities=activities
            )
        )

    return Itinerary(
        title=draft.title,
        summary=draft.summary,
        accommodation=_accommodation(draft, research, request),
        days=days,
        recommendations=draft.recommendations,
        travel_tips=draft.travel_tips,
        uncertainty_notes=draft.uncertainty_notes,
    )
