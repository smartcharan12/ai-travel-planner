"""Deterministic research queries: the same request always produces the same 5 searches.

Why fixed queries instead of letting the LLM decide what to search:

- every trip needs all five kinds of information, so there is no decision to make;
- an LLM that "decides" it already knows the hotels is exactly how invented
  hotels get into a plan;
- cost and latency are predictable (always exactly 5 searches);
- queries are plain functions of the request, so they are unit-testable and
  reproducible when debugging ("what did we search for?").

Only validated request fields are used: destination/origin passed the
place-name pattern, interests are letters-only, everything else is an enum.
``special_requirements`` (free text) is intentionally NOT put into search
queries.
"""

from __future__ import annotations

from app.schemas import (
    AccommodationType,
    DietaryPreference,
    ResearchCategory,
    ResearchQuery,
    TransportMode,
    TravelRequest,
)

_ACCOMMODATION_WORDS: dict[AccommodationType, str] = {
    AccommodationType.HOSTEL: "best hostels",
    AccommodationType.BUDGET: "best budget hotels",
    AccommodationType.MID_RANGE: "best mid-range hotels",
    AccommodationType.LUXURY: "best luxury hotels and resorts",
    AccommodationType.HOMESTAY: "best homestays",
    AccommodationType.ANY: "best places to stay",
}

_DIET_WORDS: dict[DietaryPreference, str] = {
    DietaryPreference.VEGETARIAN: "vegetarian",
    DietaryPreference.VEGAN: "vegan",
    DietaryPreference.JAIN: "Jain food",
    DietaryPreference.HALAL: "halal",
    DietaryPreference.GLUTEN_FREE: "gluten-free",
    DietaryPreference.NO_SEAFOOD: "non-seafood",
}


def _destination_query(req: TravelRequest) -> str:
    return f"{req.destination} travel guide best time to visit local tips"


def _attractions_query(req: TravelRequest) -> str:
    interests = ", ".join(req.preferences.interests)
    style = req.preferences.travel_style.value
    return f"top things to do in {req.destination} for {style} travellers interested in {interests}"


def _restaurants_query(req: TravelRequest) -> str:
    diets = " ".join(_DIET_WORDS[d] for d in req.preferences.dietary)
    prefix = f"best {diets} restaurants" if diets else "best restaurants"
    return f"{prefix} in {req.destination} with prices"


def _hotels_query(req: TravelRequest) -> str:
    words = _ACCOMMODATION_WORDS[req.preferences.accommodation]
    return f"{words} in {req.destination} price per night"


def _transport_query(req: TravelRequest) -> str:
    modes = [m.value for m in req.preferences.transport if m is not TransportMode.ANY]
    by = f" by {' or '.join(modes)}" if modes else ""
    if req.origin_city:
        return f"how to travel from {req.origin_city} to {req.destination}{by} and getting around locally"
    return f"how to get to {req.destination}{by} and local transport options"


_BUILDERS = {
    ResearchCategory.DESTINATION: _destination_query,
    ResearchCategory.ATTRACTIONS: _attractions_query,
    ResearchCategory.RESTAURANTS: _restaurants_query,
    ResearchCategory.HOTELS: _hotels_query,
    ResearchCategory.TRANSPORTATION: _transport_query,
}


def build_research_queries(request: TravelRequest) -> list[ResearchQuery]:
    """Return exactly one query per ``ResearchCategory``, in enum order."""
    return [
        ResearchQuery(category=category, destination=request.destination, text=_BUILDERS[category](request))
        for category in ResearchCategory
    ]
