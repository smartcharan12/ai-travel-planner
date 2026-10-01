"""Deterministic planning logic: pricing, optimizer, validator, assembler, quality."""

from __future__ import annotations

from datetime import date

import pytest

from app.planning.assembler import assemble_itinerary
from app.planning.optimizer import optimize_draft
from app.planning.pricing import price_for_group
from app.planning.rules import nights_for, rooms_needed
from app.planning.validator import errors_only, validate_draft
from app.schemas import CostBasis, ItineraryDraft, Pace, PriceInfo, TravelRequest
from tests.fakes import goa_draft_json, goa_research


def _draft(data=None) -> ItineraryDraft:
    return ItineraryDraft.model_validate(data or goa_draft_json())


def _request(goa_payload, **prefs) -> TravelRequest:
    goa_payload["preferences"].update(prefs)
    return TravelRequest.model_validate(goa_payload)


def _codes(issues):
    return [i.code for i in issues]


# ---------- pricing ----------
@pytest.mark.parametrize(
    "unit,quote,travelers,expected,assumed",
    [
        ("per person", "₹50 per person", 3, 150, False),
        ("for two", "₹1,500", 3, 3000, False),  # 3 people = 2 "for two" portions
        ("per night", "₹4,200 per night", 4, 4200, False),  # caller multiplies nights/rooms
        (None, "₹500", 2, 1000, True),  # unit unknown -> per person, flagged
    ],
)
def test_price_for_group(unit, quote, travelers, expected, assumed):
    price = PriceInfo(amount=float(quote.split("₹")[1].split()[0].replace(",", "")), unit=unit, quote=quote)
    cost = price_for_group(price, travelers, "INR")
    assert cost.amount == expected and cost.assumed_unit is assumed


def test_price_without_amount_is_unknown():
    assert price_for_group(PriceInfo(quote="free entry"), 2, "INR") is None
    assert price_for_group(None, 2, "INR") is None


def test_rooms_and_nights():
    assert [rooms_needed(n) for n in (1, 2, 3, 5)] == [1, 1, 2, 3]
    assert [nights_for(d) for d in (1, 2, 4)] == [0, 1, 3]


# ---------- optimizer ----------
def test_optimizer_orders_slots_and_removes_repeat_attractions():
    data = goa_draft_json()
    data["days"][0]["activities"].reverse()  # evening listed before morning
    data["days"][1]["activities"].append(
        {
            "slot": "evening",
            "activity_type": "sightseeing",
            "place_id": "A1",
            "description": "Repeat.",
        }
    )
    result = optimize_draft(_draft(data), goa_research(), Pace.MODERATE)
    day1, day2 = result.draft.days[0], result.draft.days[1]
    assert [a.slot.value for a in day1.activities] == ["morning", "evening"]
    assert "A1" not in [a.place_id for a in day2.activities]
    assert any("repeat visit to Baga Beach (A1)" in n for n in result.notes)


def test_optimizer_applies_slot_and_pace_caps_dropping_generic_first():
    data = goa_draft_json()
    generic = {
        "slot": "evening",
        "activity_type": "leisure",
        "generic_kind": "free_time",
        "description": "x",
    }
    data["days"][0]["activities"] += [
        {
            "slot": "afternoon",
            "activity_type": "food",
            "place_id": "R1",
            "description": "x",
        },
        generic,
        {
            "slot": "evening",
            "activity_type": "nightlife",
            "generic_kind": "free_time",
            "description": "x",
        },
    ]
    result = optimize_draft(_draft(data), goa_research(), Pace.RELAXED)  # cap 3
    day1 = result.draft.days[0]
    assert len(day1.activities) == 3
    assert all(a.place_id is not None for a in day1.activities)  # generic ones dropped first
    assert sum(a.slot.value == "evening" for a in day1.activities) <= 2


def test_optimizer_flags_backtracking_without_reordering():
    data = goa_draft_json()
    data["days"][0]["activities"] = [
        {
            "slot": "morning",
            "activity_type": "sightseeing",
            "place_id": "A1",
            "description": "x",
        },
        {
            "slot": "afternoon",
            "activity_type": "sightseeing",
            "place_id": "A2",
            "description": "x",
        },
        {"slot": "evening", "activity_type": "food", "place_id": "R1", "description": "x"},
    ]
    data["days"][1]["activities"] = data["days"][1]["activities"][1:]  # A2 no longer on day 2
    result = optimize_draft(_draft(data), goa_research(), Pace.MODERATE)
    assert _codes(result.warnings) == ["BACKTRACKING_RISK"]  # North Goa, Candolim, Cavelossim


# ---------- validator ----------
def test_valid_draft_has_no_errors(goa_payload):
    assert errors_only(validate_draft(_draft(), goa_research(), _request(goa_payload))) == []


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda d: d["days"].pop(), "DAY_COUNT_MISMATCH"),
        (lambda d: d["days"][2].update(activities=[]), "EMPTY_DAY"),
        (lambda d: d["days"][0]["activities"][0].update(place_id="A99"), "UNKNOWN_PLACE_ID"),
        (lambda d: d["days"][0]["activities"][0].update(place_id="H1"), "HOTEL_AS_ACTIVITY"),
        (lambda d: d.update(hotel_id="H7"), "UNKNOWN_HOTEL_ID"),
    ],
)
def test_validator_errors(goa_payload, mutate, code):
    data = goa_draft_json()
    mutate(data)
    assert code in _codes(errors_only(validate_draft(_draft(data), goa_research(), _request(goa_payload))))


def test_validator_warnings(goa_payload):
    data = goa_draft_json()
    data["hotel_id"] = None
    issues = validate_draft(_draft(data), goa_research(), _request(goa_payload, dietary=["vegetarian"]))
    assert errors_only(issues) == []
    assert {"NO_HOTEL_SELECTED", "DIETARY_UNVERIFIED"} <= set(_codes(issues))


def test_low_grounding_warning(goa_payload):
    data = goa_draft_json()
    for day in data["days"]:
        for a in day["activities"]:
            a["place_id"] = None
            a["generic_kind"] = "free_time"
    assert "LOW_GROUNDING" in _codes(validate_draft(_draft(data), goa_research(), _request(goa_payload)))


# ---------- assembler ----------
def test_assembler_adds_dates_areas_and_only_verified_prices(goa_payload):
    req = _request(goa_payload)
    itin = assemble_itinerary(_draft(), goa_research(), req)
    assert itin.days[0].calendar_date == req.start_date
    assert itin.days[3].calendar_date == date.fromordinal(req.start_date.toordinal() + 3)
    baga, dinner = itin.days[0].activities
    assert baga.area == "North Goa" and baga.estimated_cost is None and baga.cost_basis == CostBasis.UNKNOWN
    assert dinner.estimated_cost == 1500 and dinner.cost_basis == CostBasis.SOURCE  # ₹1,500 for two, 2 people
    fort = itin.days[1].activities[0]
    assert fort.estimated_cost == 100  # ₹50 per person × 2
    assert itin.accommodation.name == "Example Bay Resort"
    assert itin.accommodation.nightly_rate is None  # price was removed during grounding
    assert itin.accommodation.cost_basis == CostBasis.UNKNOWN


def test_assumed_unit_is_labelled_estimate(goa_payload):
    research = goa_research()
    research.restaurants[0].price.unit = None
    research.restaurants[0].price.quote = "₹1,500"
    dinner = assemble_itinerary(_draft(), research, _request(goa_payload)).days[0].activities[1]
    assert dinner.cost_basis == CostBasis.ESTIMATE
