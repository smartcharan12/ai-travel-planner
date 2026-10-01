"""Budget engine: every number is either a verified source price or a labelled default."""

from __future__ import annotations

import pytest

from app.planning.assembler import assemble_itinerary
from app.planning.budget import calculate_budget
from app.planning.quality import build_quality_report
from app.schemas import CostBasis, ItineraryDraft, PriceInfo, TravelRequest
from tests.fakes import goa_draft_json, goa_research


def _run(goa_payload, research=None, **overrides):
    goa_payload.update(overrides)
    req = TravelRequest.model_validate(goa_payload)
    research = research or goa_research()
    itin = assemble_itinerary(ItineraryDraft.model_validate(goa_draft_json(req.num_days)), research, req)
    budget, issues = calculate_budget(req, itin, research)
    return budget, issues, itin


def _item(budget, category):
    return next(i for i in budget.items if i.category == category)


def test_goa_budget_lines_add_up_and_show_their_working(goa_payload):
    budget, issues, _ = _run(goa_payload)
    # accommodation: no verified hotel rate -> mid_range default ₹4,000 × 3 nights × 1 room
    assert (_item(budget, "accommodation").amount, _item(budget, "accommodation").basis) == (
        12000,
        CostBasis.ESTIMATE,
    )
    # food: ₹1,200 × 2 people × 4 days
    assert _item(budget, "food").amount == 9600
    # local: verified scooter ₹400/day × 4 days × 1 scooter
    assert (_item(budget, "local_transport").amount, _item(budget, "local_transport").basis) == (
        1600,
        CostBasis.SOURCE,
    )
    # intercity: train has no verified fare -> unknown, budget incomplete
    assert _item(budget, "intercity_transport").basis == CostBasis.UNKNOWN and budget.complete is False
    # activities: only Fort Aguada has a verified price (₹50 × 2)
    assert budget.activities == 100
    subtotal = 12000 + 9600 + 1600 + 0 + 100
    assert budget.miscellaneous == pytest.approx(subtotal * 0.10)
    assert budget.total == pytest.approx(subtotal * 1.10)
    assert budget.total == pytest.approx(sum(i.amount for i in budget.items))
    assert budget.remaining == pytest.approx(25000 - budget.total)
    assert budget.per_person_total == pytest.approx(budget.total / 2)
    assert "BUDGET_INCOMPLETE" in [i.code for i in issues]


def test_verified_hotel_rate_and_intercity_fare_are_used(goa_payload):
    research = goa_research()
    research.hotels[0].price = PriceInfo(amount=4200, unit="per night", quote="₹4,200 per night")
    research.transportation[0].price = PriceInfo(amount=900, unit="per person", quote="₹900 per person")
    budget, _, itin = _run(goa_payload, research)
    assert itin.accommodation.nightly_rate == 4200
    assert (_item(budget, "accommodation").amount, _item(budget, "accommodation").basis) == (
        12600,
        CostBasis.SOURCE,
    )
    assert _item(budget, "intercity_transport").amount == 900 * 2 * 2  # 2 people, return
    assert budget.complete is True


def test_over_budget_is_a_warning_with_numbers(goa_payload):
    budget, issues, _ = _run(goa_payload, budget=10000)
    assert budget.within_budget is False and budget.remaining < 0
    over = next(i for i in issues if i.code == "OVER_BUDGET")
    assert "exceeds the budget ₹10,000" in over.message


def test_no_origin_excludes_intercity(goa_payload):
    goa_payload.pop("origin_city")
    budget, _, _ = _run(goa_payload)
    assert _item(budget, "intercity_transport").amount == 0
    assert any("no origin city" in a for a in budget.assumptions)


def test_one_day_trip_has_no_accommodation(goa_payload):
    goa_payload.pop("start_date")
    budget, _, _ = _run(goa_payload, num_days=1)
    assert budget.accommodation == 0


def test_hostel_is_priced_per_bed(goa_payload):
    goa_payload["preferences"]["accommodation"] = "hostel"
    budget, _, _ = _run(goa_payload, num_travelers=3)
    assert budget.accommodation == 800 * 3 * 3  # ₹800 × 3 nights × 3 beds


def test_other_currencies_get_no_invented_defaults(goa_payload):
    budget, _, _ = _run(goa_payload, currency="USD")
    assert _item(budget, "food").basis == CostBasis.UNKNOWN and budget.food == 0
    assert budget.complete is False


def test_quality_report(goa_payload):
    budget, issues, itin = _run(goa_payload)
    report = build_quality_report(itin, budget, issues, repair_attempts=1, optimization_notes=["x"])
    # 6 activities, 4 reference places (A1, R1, A2, T2), 2 generic
    assert report.grounded_activity_ratio == pytest.approx(4 / 6, abs=1e-3)
    assert report.sourced_cost_ratio == pytest.approx((1600 + 100) / budget.total, abs=1e-3)
    assert report.repair_attempts == 1 and report.optimization_notes == ["x"]
