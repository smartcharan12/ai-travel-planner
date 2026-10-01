"""Fallback cost heuristics for the budget engine, used ONLY when no source price exists.

IMPORTANT: these are rough round numbers chosen by the developer as
placeholders. They are NOT researched, NOT current and NOT specific to any
destination. Every figure taken from here is labelled ``basis: "estimate"``
in the response, and the exact rate is written into ``assumptions``.
Adjust them for your market before relying on budgets.

Rates exist only for INR. For other currencies the engine reports the
category as unknown instead of converting made-up numbers.
"""

from __future__ import annotations

from app.schemas import AccommodationType

# Per room per night (hostel: per bed per night).
NIGHTLY_ROOM_RATE_INR: dict[AccommodationType, float] = {
    AccommodationType.HOSTEL: 800,
    AccommodationType.BUDGET: 1_500,
    AccommodationType.HOMESTAY: 2_000,
    AccommodationType.ANY: 3_000,
    AccommodationType.MID_RANGE: 4_000,
    AccommodationType.LUXURY: 12_000,
}

# Per person per day, all meals.
FOOD_PER_PERSON_DAY_INR: dict[AccommodationType, float] = {
    AccommodationType.HOSTEL: 500,
    AccommodationType.BUDGET: 700,
    AccommodationType.HOMESTAY: 800,
    AccommodationType.ANY: 1_000,
    AccommodationType.MID_RANGE: 1_200,
    AccommodationType.LUXURY: 3_000,
}

LOCAL_TRANSPORT_PER_PERSON_DAY_INR = 300.0

# Share of the subtotal set aside for tips, snacks, small purchases, surprises.
MISC_SHARE = 0.10

SUPPORTED_CURRENCY = "INR"
