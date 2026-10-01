"""Verify the LLM's extraction against the search results it was given.

This is the main hallucination control of Stage 2. The LLM *proposes*
entities; this module, plain Python with no AI involved, decides which ones
are kept. For every extracted entity:

1. its ``source_id`` must be one of the SearchHits we actually sent;
   otherwise it is rejected (UNKNOWN_SOURCE_ID)
2. its name must literally appear (ignoring case, accents, punctuation) in
   that hit's title or content; otherwise it is rejected (NAME_NOT_IN_SOURCE).
   This catches the classic failure: the model "remembers" a famous place
   and attaches it to a source that never mentions it.
3. duplicates (same type, same folded name) are rejected (DUPLICATE)
4. at most N per type are kept (OVER_LIMIT)
5. a price survives only if its quote appears in the cited source AND the
   amount's digits appear in the quote; otherwise the price, not the
   entity, is removed. A price is never estimated here.

Accepted entities get fresh ids (A1.., R1.., H1.., T1..) assigned by us.

Honest limitation: a name check proves the place is *mentioned* by the
source, not that every descriptive sentence the model wrote is supported.
Description faithfulness is measured offline with DeepEval (later stage).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from app.research.text import contains_phrase, fold
from app.schemas import (
    Attraction,
    CostBasis,
    DestinationInfo,
    ExtractedPrice,
    GroundingReport,
    Hotel,
    PriceInfo,
    RejectedEntity,
    RemovedPrice,
    ResearchExtraction,
    ResearchResult,
    Restaurant,
    SearchHit,
    Transportation,
)


def _amount_digits(amount: float) -> str:
    return str(int(amount)) if float(amount).is_integer() else str(amount)


def verify_price(price: ExtractedPrice, hit: SearchHit) -> tuple[PriceInfo | None, str | None]:
    """Return (verified price, None) or (None, reason it was removed)."""
    if not contains_phrase(f"{hit.title} {hit.content}", price.quote):
        return None, "QUOTE_NOT_IN_SOURCE"
    if price.amount is not None:
        # "₹2,500" and "Rs. 2500" both contain the digits 2500 once separators are removed.
        quote_digits = "".join(ch for ch in price.quote if ch.isdigit() or ch == ".")
        if _amount_digits(price.amount) not in quote_digits:
            return None, "AMOUNT_NOT_IN_QUOTE"
    currency = price.currency.upper() if price.currency and len(price.currency) == 3 else None
    return (
        PriceInfo(
            amount=price.amount,
            currency=currency,
            unit=price.unit,
            quote=price.quote,
            basis=CostBasis.SOURCE,
        ),
        None,
    )


class _Grounder:
    def __init__(self, hits: Sequence[SearchHit], max_per_type: int):
        self.hits = {h.source_id: h for h in hits}
        self.max_per_type = max_per_type
        self.rejected: list[RejectedEntity] = []
        self.prices_removed: list[RemovedPrice] = []

    def ground(
        self,
        entity_type: str,
        prefix: str,
        extracted: Sequence[Any],
        build: Callable[[Any, str, PriceInfo | None], Any],
    ) -> list[Any]:
        accepted: list[Any] = []
        seen: set[str] = set()
        for item in extracted:
            hit = self.hits.get(item.source_id)
            reason = None
            if hit is None:
                reason = "UNKNOWN_SOURCE_ID"
            elif not contains_phrase(f"{hit.title} {hit.content}", item.name):
                reason = "NAME_NOT_IN_SOURCE"
            elif fold(item.name) in seen:
                reason = "DUPLICATE"
            elif len(accepted) >= self.max_per_type:
                reason = "OVER_LIMIT"
            if reason:
                self.rejected.append(
                    RejectedEntity(
                        entity_type=entity_type, name=item.name, source_id=item.source_id, reason=reason
                    )
                )
                continue

            seen.add(fold(item.name))
            entity_id = f"{prefix}{len(accepted) + 1}"
            price = None
            if getattr(item, "price", None) is not None:
                price, price_reason = verify_price(item.price, hit)
                if price_reason:
                    self.prices_removed.append(
                        RemovedPrice(entity_id=entity_id, quote=item.price.quote, reason=price_reason)
                    )
            accepted.append(build(item, entity_id, price))
        return accepted

    def destination_info(self, extraction: ResearchExtraction, destination: str) -> DestinationInfo | None:
        info = extraction.destination_info
        if info is None:
            return None
        valid_ids = [sid for sid in dict.fromkeys(info.source_ids) if sid in self.hits]
        if not valid_ids:
            self.rejected.append(
                RejectedEntity(
                    entity_type="destination_info",
                    name=destination,
                    source_id=None,
                    reason="NO_VALID_SOURCES",
                )
            )
            return None
        return DestinationInfo(
            name=destination,
            summary=info.summary,
            best_time_to_visit=info.best_time_to_visit,
            local_tips=info.local_tips,
            source_ids=valid_ids,
        )


def ground_extraction(
    extraction: ResearchExtraction,
    hits: Sequence[SearchHit],
    *,
    destination: str,
    searched_at: datetime,
    max_per_type: int,
    warnings: Sequence[str] = (),
) -> tuple[ResearchResult, GroundingReport]:
    """Apply every grounding rule and build the verified ``ResearchResult``."""
    g = _Grounder(hits, max_per_type)

    attractions = g.ground(
        "attraction",
        "A",
        extraction.attractions,
        lambda e, i, p: Attraction(
            id=i,
            name=e.name,
            area=e.area,
            source_id=e.source_id,
            description=e.description,
            category=e.category,
            typical_duration_hours=e.typical_duration_hours,
            price=p,
        ),
    )
    restaurants = g.ground(
        "restaurant",
        "R",
        extraction.restaurants,
        lambda e, i, p: Restaurant(
            id=i,
            name=e.name,
            area=e.area,
            source_id=e.source_id,
            description=e.description,
            cuisine=e.cuisine,
            dietary_notes=e.dietary_notes,
            price=p,
        ),
    )
    hotels = g.ground(
        "hotel",
        "H",
        extraction.hotels,
        lambda e, i, p: Hotel(
            id=i,
            name=e.name,
            area=e.area,
            source_id=e.source_id,
            description=e.description,
            accommodation_type=e.accommodation_type,
            price=p,
        ),
    )
    transportation = g.ground(
        "transportation",
        "T",
        extraction.transportation,
        lambda e, i, p: Transportation(
            id=i,
            name=e.name,
            area=e.area,
            source_id=e.source_id,
            mode=e.mode,
            scope=e.scope,
            description=e.description,
            duration_note=e.duration_note,
            price=p,
        ),
    )
    destination_info = g.destination_info(extraction, destination)

    # Return only sources that something actually cites, so the user's source list is meaningful.
    cited = {e.source_id for group in (attractions, restaurants, hotels, transportation) for e in group}
    if destination_info:
        cited.update(destination_info.source_ids)
    sources = [h.to_source() for h in hits if h.source_id in cited]

    research = ResearchResult(
        destination_info=destination_info,
        attractions=attractions,
        restaurants=restaurants,
        hotels=hotels,
        transportation=transportation,
        sources=sources,
        warnings=list(warnings),
        uncertainty_notes=extraction.uncertainty_notes,
        searched_at=searched_at,
    )
    extracted_count = (
        len(extraction.attractions)
        + len(extraction.restaurants)
        + len(extraction.hotels)
        + len(extraction.transportation)
        + (1 if extraction.destination_info else 0)
    )
    accepted_count = (
        len(attractions)
        + len(restaurants)
        + len(hotels)
        + len(transportation)
        + (1 if destination_info else 0)
    )
    report = GroundingReport(
        extracted=extracted_count,
        accepted=accepted_count,
        rejected=g.rejected,
        prices_removed=g.prices_removed,
    )
    return research, report
