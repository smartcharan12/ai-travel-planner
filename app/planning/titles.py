"""Activity titles are written by code, never by the LLM.

A title is the most visible place a venue name appears. Generating it from
the verified entity (or the generic kind) guarantees that every name in a
title comes from research.
"""

from __future__ import annotations

from app.schemas import ActivityType, GenericActivity, TimeSlot

_GENERIC_TITLES: dict[GenericActivity, str] = {
    GenericActivity.FREE_TIME: "Free time",
    GenericActivity.REST_AT_HOTEL: "Rest at your hotel",
    GenericActivity.CHECK_IN: "Check in at your hotel",
    GenericActivity.CHECK_OUT: "Check out of your hotel",
    GenericActivity.ARRIVAL: "Arrive in {destination}",
    GenericActivity.DEPARTURE: "Depart from {destination}",
    GenericActivity.MEAL_NEAR_HOTEL: "Meal near your hotel",
    GenericActivity.EXPLORE_NEARBY: "Explore the area around your hotel",
}

_MEALS = {TimeSlot.MORNING: "Breakfast", TimeSlot.AFTERNOON: "Lunch", TimeSlot.EVENING: "Dinner"}

_VENUE_TEMPLATES: dict[ActivityType, str] = {
    ActivityType.SIGHTSEEING: "Visit {name}",
    ActivityType.LEISURE: "Relax at {name}",
    ActivityType.NIGHTLIFE: "Evening out at {name}",
    ActivityType.SHOPPING: "Shop at {name}",
    ActivityType.TRANSIT: "Get around by {name}",
}


def activity_title(
    *,
    slot: TimeSlot,
    activity_type: ActivityType,
    place_name: str | None,
    generic_kind: GenericActivity | None,
    destination: str,
) -> str:
    if place_name:
        if activity_type is ActivityType.FOOD:
            return f"{_MEALS[slot]} at {place_name}"
        return _VENUE_TEMPLATES[activity_type].format(name=place_name)
    if generic_kind:
        return _GENERIC_TITLES[generic_kind].format(destination=destination)
    return "Free time"  # unreachable after validation; kept total for safety


def short_label(place_name: str | None, generic_kind: GenericActivity | None) -> str:
    """Compact label for optimizer notes and logs."""
    if place_name:
        return place_name
    return generic_kind.value.replace("_", " ") if generic_kind else "unspecified activity"
