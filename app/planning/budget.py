"""Deterministic budget engine. No LLM involved.

Why code and not the LLM: language models are unreliable at multi-step
arithmetic (and confident when wrong). A budget is a few multiplications
and a sum. Code gets that right every time, and every line can show its
working.

Source of each category, in order of preference:

- accommodation: hotel's verified per-night rate × nights × rooms;
  else tier default per room (per bed for hostels) per night.
- food: tier default per person per day (restaurant prices are per meal; see note).
- local_transport: verified per-day local option × days × vehicles (one per two people);
  else default per person per day.
- intercity_transport: verified intercity fare for the group × 2 (return);
  else unknown, and the budget is marked incomplete.
- activities: sum of scheduled activities with verified prices; unpriced ones count
  as 0 and are listed in ``assumptions``.
- miscellaneous: 10% of the subtotal.

Food uses a daily allowance even when restaurant prices are known: the
itinerary names some meals, not all, so adding per-meal prices *and* a
daily allowance would double-count.

Fallback rates live in ``budget_rates.py`` and exist only for INR.
"""

from __future__ import annotations

from app.planning.budget_rates import (
    FOOD_PER_PERSON_DAY_INR,
    LOCAL_TRANSPORT_PER_PERSON_DAY_INR,
    MISC_SHARE,
    NIGHTLY_ROOM_RATE_INR,
    SUPPORTED_CURRENCY,
)
from app.planning.pricing import format_money, price_for_group
from app.planning.rules import nights_for, rooms_needed
from app.schemas import (
    AccommodationType,
    ActivityType,
    BudgetBreakdown,
    BudgetLineItem,
    CostBasis,
    IssueSeverity,
    Itinerary,
    ResearchResult,
    TravelRequest,
    ValidationIssue,
)

_PAID_ACTIVITY_TYPES = {
    ActivityType.SIGHTSEEING,
    ActivityType.LEISURE,
    ActivityType.NIGHTLIFE,
    ActivityType.SHOPPING,
}


class _Builder:
    def __init__(self, request: TravelRequest):
        self.request = request
        self.cur = request.currency
        self.has_defaults = request.currency == SUPPORTED_CURRENCY
        self.items: list[BudgetLineItem] = []
        self.assumptions: list[str] = []
        self.complete = True

    def money(self, amount: float) -> str:
        return format_money(amount, self.cur)

    def add(self, category: str, amount: float, basis: CostBasis, detail: str) -> None:
        self.items.append(
            BudgetLineItem(category=category, amount=round(amount, 2), basis=basis, detail=detail)
        )

    def unknown(self, category: str, reason: str) -> None:
        self.complete = False
        self.assumptions.append(f"{category}: {reason} Counted as 0.")
        self.add(category, 0, CostBasis.UNKNOWN, reason)


def calculate_budget(
    request: TravelRequest, itinerary: Itinerary, research: ResearchResult
) -> tuple[BudgetBreakdown, list[ValidationIssue]]:
    b = _Builder(request)
    n, days = request.num_travelers, request.num_days
    nights, rooms = nights_for(days), rooms_needed(n)
    tier = request.preferences.accommodation

    # ---- accommodation ----
    acc = itinerary.accommodation
    if nights == 0:
        b.add("accommodation", 0, CostBasis.ESTIMATE, "1-day trip: no overnight stay.")
    elif acc and acc.nightly_rate is not None:
        source = next((h.source_id for h in research.hotels if h.id == acc.hotel_id), "?")
        b.add(
            "accommodation",
            acc.nightly_rate * nights * rooms,
            CostBasis.SOURCE,
            f"{b.money(acc.nightly_rate)}/night × {nights} nights × {rooms} room(s), {acc.name} ({source})",
        )
    elif b.has_defaults:
        per_bed = tier is AccommodationType.HOSTEL
        rate, units = NIGHTLY_ROOM_RATE_INR[tier], (n if per_bed else rooms)
        unit_name = "bed" if per_bed else "room"
        b.add(
            "accommodation",
            rate * nights * units,
            CostBasis.ESTIMATE,
            f"{b.money(rate)}/{unit_name}/night × {nights} nights × {units} {unit_name}(s)",
        )
        b.assumptions.append(
            f"accommodation: no verified nightly rate; used the default {b.money(rate)} per {unit_name} "
            f"per night for '{tier.value}'."
        )
    else:
        b.unknown("accommodation", f"No verified nightly rate and no default rates for {b.cur}.")

    # ---- food ----
    if b.has_defaults:
        rate = FOOD_PER_PERSON_DAY_INR[tier]
        b.add("food", rate * n * days, CostBasis.ESTIMATE, f"{b.money(rate)}/person/day × {n} × {days} days")
        b.assumptions.append(
            f"food: default allowance {b.money(rate)} per person per day for '{tier.value}' "
            "(restaurant prices are shown per meal and not added, to avoid double counting)."
        )
    else:
        b.unknown("food", f"No default food allowance for {b.cur}.")

    # ---- local transport ----
    local = next(
        (
            t
            for t in research.transportation
            if t.scope == "local"
            and t.price
            and t.price.amount is not None
            and "day" in f"{t.price.unit} {t.price.quote}".lower()
        ),
        None,
    )
    if local:
        b.add(
            "local_transport",
            local.price.amount * days * rooms,
            CostBasis.SOURCE,
            f"{local.name}: {b.money(local.price.amount)}/day × {days} days × {rooms} (one per two people) "
            f"({local.source_id})",
        )
    elif b.has_defaults:
        rate = LOCAL_TRANSPORT_PER_PERSON_DAY_INR
        b.add(
            "local_transport",
            rate * n * days,
            CostBasis.ESTIMATE,
            f"{b.money(rate)}/person/day × {n} × {days}",
        )
        b.assumptions.append(f"local transport: default {b.money(rate)} per person per day.")
    else:
        b.unknown("local_transport", f"No verified local transport price and no default for {b.cur}.")

    # ---- intercity transport ----
    if not request.origin_city:
        b.add(
            "intercity_transport",
            0,
            CostBasis.ESTIMATE,
            "No origin city given; travel to the destination not included.",
        )
        b.assumptions.append("intercity transport: not included because no origin city was given.")
    else:
        fare = next(
            (
                t
                for t in research.transportation
                if t.scope == "intercity" and t.price and t.price.amount is not None
            ),
            None,
        )
        group = price_for_group(fare.price, n, b.cur) if fare else None
        if group:
            b.add(
                "intercity_transport",
                group.amount * 2,
                CostBasis.SOURCE,
                f"{fare.name}: {group.explanation} × 2 (return) ({fare.source_id})",
            )
            if group.assumed_unit:
                b.assumptions.append(
                    "intercity transport: fare unit not stated by the source; assumed per person."
                )
        else:
            b.unknown("intercity_transport", f"No verified fare found from {request.origin_city}.")

    # ---- activities ----
    priced = unpriced = 0
    activity_total = 0.0
    for day in itinerary.days:
        for a in day.activities:
            if a.activity_type not in _PAID_ACTIVITY_TYPES or a.place_id is None:
                continue
            if a.estimated_cost is not None:
                priced += 1
                activity_total += a.estimated_cost
            else:
                unpriced += 1
    b.add(
        "activities",
        activity_total,
        CostBasis.SOURCE if priced else CostBasis.ESTIMATE,
        f"{priced} activity price(s) from sources",
    )
    if unpriced:
        b.assumptions.append(
            f"activities: {unpriced} scheduled place(s) have no verified price and are counted as 0 "
            "(many are free, but check)."
        )

    # ---- miscellaneous ----
    subtotal = sum(i.amount for i in b.items)
    b.add(
        "miscellaneous",
        subtotal * MISC_SHARE,
        CostBasis.ESTIMATE,
        f"{MISC_SHARE:.0%} of subtotal {b.money(subtotal)}",
    )

    by_cat = {i.category: i.amount for i in b.items}
    total = round(sum(by_cat.values()), 2)
    remaining = round(request.budget - total, 2)
    breakdown = BudgetBreakdown(
        currency=b.cur,
        accommodation=by_cat["accommodation"],
        food=by_cat["food"],
        local_transport=by_cat["local_transport"],
        intercity_transport=by_cat["intercity_transport"],
        activities=by_cat["activities"],
        miscellaneous=by_cat["miscellaneous"],
        total=total,
        budget=request.budget,
        remaining=remaining,
        within_budget=remaining >= 0,
        per_person_total=round(total / n, 2),
        assumptions=b.assumptions,
        items=b.items,
        complete=b.complete,
    )

    issues: list[ValidationIssue] = []
    if remaining < 0:
        pct = -remaining / request.budget * 100
        issues.append(
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                code="OVER_BUDGET",
                message=f"Estimated total {b.money(total)} exceeds the budget {b.money(request.budget)} "
                f"by {b.money(-remaining)} ({pct:.0f}%).",
            )
        )
    if not b.complete:
        issues.append(
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                code="BUDGET_INCOMPLETE",
                message="Some costs are unknown and counted as 0, so the real total will be higher.",
            )
        )
    return breakdown, issues
