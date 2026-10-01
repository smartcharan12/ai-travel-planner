"""Turn a verified source price ("₹50 per person") into a cost for the whole group.

Units are read from the price's ``unit`` and ``quote`` text. When the unit
is unclear we assume *per person*: over-estimating is the safer mistake
for a budget, and the assumption is reported to the user.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.schemas import PriceInfo

_PER_PERSON = ("per person", "per head", "per adult", "per pax", "/person")
_FOR_TWO = ("for two", "for 2")
_PER_UNIT = ("per night", "per room", "per day", "per vehicle", "per group", "per car", "per scooter")


@dataclass(frozen=True)
class GroupCost:
    amount: float
    explanation: str
    assumed_unit: bool = False


def format_money(amount: float, currency: str) -> str:
    symbol = "₹" if currency == "INR" else f"{currency} "
    sign = "−" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.0f}"


def price_for_group(price: PriceInfo | None, travelers: int, currency: str) -> GroupCost | None:
    """Cost of one use of this item by the whole group, or None if no amount is known.

    'Per night/day/vehicle' prices are returned as-is (one unit); the caller
    multiplies by nights, days or rooms because only it knows those.
    """
    if price is None or price.amount is None:
        return None
    text = f"{price.unit or ''} {price.quote}".lower()
    shown = format_money(price.amount, currency)
    if any(k in text for k in _PER_UNIT):
        return GroupCost(price.amount, f"{shown} {price.unit or ''}".strip())
    if any(k in text for k in _FOR_TWO):
        pairs = math.ceil(travelers / 2)
        return GroupCost(price.amount * pairs, f"{shown} for two × {pairs}")
    if any(k in text for k in _PER_PERSON):
        return GroupCost(price.amount * travelers, f"{shown} per person × {travelers}")
    return GroupCost(
        price.amount * travelers,
        f"{shown} × {travelers} (unit not stated; assumed per person)",
        assumed_unit=True,
    )
