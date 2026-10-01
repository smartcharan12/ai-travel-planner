"""Grounding: the deterministic hallucination filter applied to LLM extraction."""

from __future__ import annotations

from datetime import UTC, datetime

from app.research.grounding import ground_extraction
from app.schemas import CostBasis, ResearchCategory, ResearchExtraction
from tests.fakes import goa_extraction_json, make_hit

C = ResearchCategory
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _goa_hits():
    return [
        make_hit(
            "S1", "Goa is best visited between November and February. Rent a scooter.", category=C.DESTINATION
        ),
        make_hit(
            "S2",
            "Baga Beach in North Goa is known for nightlife. Fort Aguada near Candolim is a "
            "17th-century fort. Entry fee: ₹50 per person.",
        ),
        make_hit(
            "S3",
            "Fisherman's Wharf in Cavelossim, Goa serves Goan seafood; a meal for two costs about ₹1,500.",
            category=C.RESTAURANTS,
        ),
        make_hit(
            "S4", "Example Bay Resort in Calangute, Goa has rooms from ₹4,200 per night.", category=C.HOTELS
        ),
        make_hit(
            "S5",
            "The overnight train from Bengaluru to Goa takes about 12 hours. "
            "In Goa, scooter rental costs ₹400 per day.",
            category=C.TRANSPORTATION,
        ),
    ]


def _ground(extraction_dict, hits=None, max_per_type=8):
    return ground_extraction(
        ResearchExtraction.model_validate(extraction_dict),
        hits or _goa_hits(),
        destination="Goa",
        searched_at=NOW,
        max_per_type=max_per_type,
    )


def test_supported_entities_are_kept_with_traceable_sources():
    research, report = _ground(goa_extraction_json())
    names = [a.name for a in research.attractions]
    assert names == ["Baga Beach", "Fort Aguada"]
    # Traceability: entity -> source id -> URL
    fort = research.attractions[1]
    source = next(s for s in research.sources if s.id == fort.source_id)
    assert source.url == "https://example.com/S2"
    assert report.extracted == 8 and report.accepted == 7


def test_place_not_mentioned_in_cited_source_is_rejected():
    _, report = _ground(goa_extraction_json())
    assert [(r.name, r.reason) for r in report.rejected] == [("Dudhsagar Falls", "NAME_NOT_IN_SOURCE")]


def test_unknown_source_id_is_rejected():
    data = {"attractions": [{"name": "Baga Beach", "source_id": "S99", "description": "x"}]}
    research, report = _ground(data)
    assert research.attractions == []
    assert report.rejected[0].reason == "UNKNOWN_SOURCE_ID"


def test_duplicates_and_over_limit_are_rejected():
    data = {
        "attractions": [
            {"name": "Baga Beach", "source_id": "S2", "description": "x"},
            {"name": "baga  beach", "source_id": "S2", "description": "dup"},
            {"name": "Fort Aguada", "source_id": "S2", "description": "x"},
        ]
    }
    research, report = _ground(data, max_per_type=1)
    assert [a.id for a in research.attractions] == ["A1"]
    assert [r.reason for r in report.rejected] == ["DUPLICATE", "OVER_LIMIT"]


def test_quoted_price_found_in_source_is_kept_as_source_basis():
    research, _ = _ground(goa_extraction_json())
    fee = research.attractions[1].price
    assert (fee.amount, fee.currency, fee.basis) == (50, "INR", CostBasis.SOURCE)
    assert research.restaurants[0].price.quote == "₹1,500"


def test_price_amount_that_disagrees_with_quote_is_removed_not_guessed():
    research, report = _ground(goa_extraction_json())
    assert research.hotels[0].price is None  # model said 3000, source says 4,200
    assert [(p.entity_id, p.reason) for p in report.prices_removed] == [("H1", "AMOUNT_NOT_IN_QUOTE")]


def test_price_quote_not_in_source_is_removed():
    data = {
        "hotels": [
            {
                "name": "Example Bay Resort",
                "source_id": "S4",
                "price": {"quote": "₹9,999 per night", "amount": 9999},
            }
        ]
    }
    research, report = _ground(data)
    assert research.hotels[0].price is None
    assert report.prices_removed[0].reason == "QUOTE_NOT_IN_SOURCE"


def test_entity_ids_are_assigned_by_code_per_type():
    research, _ = _ground(goa_extraction_json())
    assert [t.id for t in research.transportation] == ["T1", "T2"]
    assert research.restaurants[0].id == "R1" and research.hotels[0].id == "H1"
    assert research.entity_ids() == {"A1", "A2", "R1", "H1", "T1", "T2"}


def test_destination_info_keeps_only_valid_source_ids():
    data = goa_extraction_json()
    data["destination_info"]["source_ids"] = ["S1", "S77"]
    research, _ = _ground(data)
    assert research.destination_info.source_ids == ["S1"]


def test_destination_info_without_any_valid_source_is_dropped():
    data = goa_extraction_json()
    data["destination_info"]["source_ids"] = ["S77"]
    research, report = _ground(data)
    assert research.destination_info is None
    assert report.rejected[-1].reason == "NO_VALID_SOURCES"


def test_only_cited_sources_are_listed():
    data = {"attractions": [{"name": "Baga Beach", "source_id": "S2", "description": "x"}]}
    research, _ = _ground(data)
    assert [s.id for s in research.sources] == ["S2"]


def test_uncertainty_notes_are_preserved():
    research, _ = _ground(goa_extraction_json())
    assert research.uncertainty_notes == ["No vegetarian-specific restaurants were found in the sources."]
