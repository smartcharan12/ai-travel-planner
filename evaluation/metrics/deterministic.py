"""Deterministic evaluation metrics (DeepEval ``BaseMetric`` subclasses).

Why code, not an LLM judge, for these: each is a question with a single
correct answer that code can check exactly and for free:

- "Is every scheduled place_id a verified entity?"            -> set membership
- "Does the budget add up?"                                     -> arithmetic
- "Are there exactly N days, numbered 1..N?"                   -> counting
- "Does any text name a place absent from verified research?"  -> the same detector the app uses

Asking an LLM judge "is ₹25,630 the correct sum of these six lines?" would be
slower, cost money, and sometimes be wrong.

Each metric reads the structured request/response from ``test_case.metadata``
and produces score (0..1), reason and success, like any DeepEval metric, so it
also works with ``deepeval.assert_test``.
"""

from __future__ import annotations

import math

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from app.planning.named_places import unsupported_names
from app.planning.rules import MAX_ACTIVITIES_BY_PACE, rooms_needed
from app.planning.validator import research_evidence
from app.research.text import contains_phrase
from app.schemas import ActivityType, TravelRequest, TravelResponse
from evaluation.config import threshold


class _DeterministicMetric(BaseMetric):
    """Shared plumbing: parse metadata, store score/reason/success, sync and async APIs."""

    metric_name = "base"
    kind = "deterministic"

    def __init__(self, threshold_value: float | None = None):
        self.threshold = threshold(self.metric_name) if threshold_value is None else threshold_value
        self.score = None
        self.reason = None
        self.success = None
        self.include_reason = True
        self.async_mode = False
        self.strict_mode = False
        self.verbose_mode = False
        self.error = None

    @property
    def __name__(self) -> str:  # DeepEval displays metrics by this name
        return self.metric_name

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        req = TravelRequest.model_validate(test_case.metadata["request"])
        resp = TravelResponse.model_validate(test_case.metadata["response"])
        score, reason = self.evaluate(req, resp)
        self.score, self.reason = round(score, 4), reason
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

    def evaluate(self, req: TravelRequest, resp: TravelResponse) -> tuple[float, str]:
        raise NotImplementedError


def _checks(results: list[tuple[bool, str]]) -> tuple[float, str]:
    """Score = share of passed checks; reason lists the failures (or 'all checks passed')."""
    failed = [msg for ok, msg in results if not ok]
    score = (len(results) - len(failed)) / len(results) if results else 1.0
    return score, "all checks passed" if not failed else "; ".join(failed)


class EntityGroundingMetric(_DeterministicMetric):
    """Grounding: every activity is a verified entity (by id) or an explicit generic activity,
    and every entity used traces to a returned source."""

    metric_name = "entity_grounding"

    def evaluate(self, req, resp):
        entities = resp.research.entity_index()
        source_ids = {s.id for s in resp.sources}
        problems, total = [], 0
        for day in resp.itinerary.days:
            for a in day.activities:
                total += 1
                if a.place_id is None and a.generic_kind is None:
                    problems.append(f"day {day.day_number}: activity has neither place_id nor generic_kind")
                elif a.place_id is not None and a.place_id not in entities:
                    problems.append(f"day {day.day_number}: unknown place_id {a.place_id}")
                elif a.place_id is not None and entities[a.place_id].source_id not in source_ids:
                    problems.append(f"day {day.day_number}: {a.place_id} cites a source not returned")
        score = (total - len(problems)) / total if total else 0.0
        return score, "; ".join(problems) or f"{total}/{total} activities grounded or explicitly generic"


class UnsupportedPlaceMetric(_DeterministicMetric):
    """Hallucination resistance: no LLM-visible text names a place absent from verified research."""

    metric_name = "unsupported_places"

    def evaluate(self, req, resp):
        evidence = research_evidence(resp.research, req)
        it = resp.itinerary
        texts = [it.title, it.summary, *it.recommendations, *it.travel_tips]
        for day in it.days:
            texts.append(day.theme)
            texts += [f"{a.title}. {a.description}" for a in day.activities]
        names = sorted({n for t in texts for n in unsupported_names(t, evidence)})
        return (
            (0.0, "unsupported place names: " + ", ".join(names)) if names else (1.0, "no unsupported names")
        )


class CompletenessMetric(_DeterministicMetric):
    """Completeness: requested days, dates, non-empty days, required sections present."""

    metric_name = "completeness"

    def evaluate(self, req, resp):
        it, days = resp.itinerary, resp.itinerary.days
        results = [
            (
                [d.day_number for d in days] == list(range(1, req.num_days + 1)),
                f"expected days 1..{req.num_days}, got {[d.day_number for d in days]}",
            ),
            (all(d.activities for d in days), "a day has no activities"),
            (bool(it.title and it.summary), "title or summary missing"),
            (
                {i.category for i in resp.budget.items}
                >= {
                    "accommodation",
                    "food",
                    "local_transport",
                    "intercity_transport",
                    "activities",
                    "miscellaneous",
                },
                "budget categories missing",
            ),
            (bool(resp.sources), "no sources returned"),
        ]
        if req.start_date:
            results.append((all(d.calendar_date is not None for d in days), "a day is missing its date"))
        return _checks(results)


class BudgetConstraintMetric(_DeterministicMetric):
    """Budget: the arithmetic is exact, and exceeding the budget is never hidden."""

    metric_name = "budget_constraint"

    def evaluate(self, req, resp):
        b = resp.budget
        line_sum = sum(i.amount for i in b.items)
        warned_over = any(i.code == "OVER_BUDGET" for i in resp.quality.issues)
        results = [
            (math.isclose(line_sum, b.total, abs_tol=0.01), f"lines sum to {line_sum}, total says {b.total}"),
            (math.isclose(b.remaining, req.budget - b.total, abs_tol=0.01), "remaining != budget - total"),
            (
                math.isclose(b.per_person_total, b.total / req.num_travelers, abs_tol=0.01),
                "per-person total wrong",
            ),
            (b.currency == req.currency, f"currency {b.currency} != requested {req.currency}"),
            (b.within_budget == (b.total <= req.budget), "within_budget flag inconsistent"),
            (b.within_budget or warned_over, "over budget but no OVER_BUDGET warning"),
        ]
        return _checks(results)


_INTEREST_TERMS: dict[str, tuple[str, ...]] = {
    "beaches": ("beach",),
    "food": ("food", "restaurant", "cuisine"),
    "nightlife": ("nightlife", "bar", "pub", "club"),
    "history": ("history", "historic", "heritage", "fort", "palace", "museum", "monument", "tomb"),
    "culture": ("culture", "cultural", "heritage", "temple", "art", "museum"),
    "shopping": ("shopping", "market", "bazaar", "mall"),
    "nature": ("nature", "park", "garden", "lake", "hill", "waterfall", "forest"),
    "adventure": ("adventure", "trek", "hike", "rafting", "climbing", "paragliding"),
    "relaxation": ("relax", "spa", "resort", "beach"),
}
_INTEREST_TYPES = {
    "food": ActivityType.FOOD,
    "nightlife": ActivityType.NIGHTLIFE,
    "shopping": ActivityType.SHOPPING,
}


class PreferenceMatchMetric(_DeterministicMetric):
    """Relevance (approximate): share of requested interests served by at least one scheduled
    verified place. Matching uses activity types and a small term map, so it is a coarse proxy;
    the LLM judge's 'preference_alignment' covers nuance."""

    metric_name = "preference_match"

    def evaluate(self, req, resp):
        entities = resp.research.entity_index()
        scheduled = [a for d in resp.itinerary.days for a in d.activities if a.place_id in entities]
        covered, missing = [], []
        for interest in req.preferences.interests:
            terms = _INTEREST_TERMS.get(interest, (interest,))
            hit = False
            for a in scheduled:
                e = entities[a.place_id]
                text = " ".join(
                    filter(
                        None,
                        [
                            e.name,
                            e.area,
                            getattr(e, "category", None),
                            getattr(e, "description", None),
                            getattr(e, "cuisine", None),
                        ],
                    )
                )
                if _INTEREST_TYPES.get(interest) == a.activity_type or any(
                    contains_phrase(text, t) for t in terms
                ):
                    hit = True
                    break
            (covered if hit else missing).append(interest)
        score = len(covered) / len(req.preferences.interests)
        return score, f"covered {covered}" + (f"; not covered {missing}" if missing else "")


class ConstraintAdherenceMetric(_DeterministicMetric):
    """Constraints: pace cap, rooms for the group, dietary needs handled honestly, no repeats."""

    metric_name = "constraint_adherence"

    def evaluate(self, req, resp):
        cap = MAX_ACTIVITIES_BY_PACE[req.preferences.pace]
        codes = {i.code for i in resp.quality.issues}
        attractions = {a.id for a in resp.research.attractions}
        scheduled_attractions = [
            a.place_id for d in resp.itinerary.days for a in d.activities if a.place_id in attractions
        ]
        results = [
            (
                all(len(d.activities) <= cap for d in resp.itinerary.days),
                f"a day exceeds {cap} activities for '{req.preferences.pace.value}' pace",
            ),
            (
                len(scheduled_attractions) == len(set(scheduled_attractions)),
                "an attraction is scheduled twice",
            ),
        ]
        if resp.itinerary.accommodation:
            results.append(
                (
                    resp.itinerary.accommodation.rooms == rooms_needed(req.num_travelers),
                    f"rooms != {rooms_needed(req.num_travelers)} for {req.num_travelers} travellers",
                )
            )
        if req.preferences.dietary:
            entities = resp.research.entity_index()
            food = [
                a
                for d in resp.itinerary.days
                for a in d.activities
                if a.place_id in entities and a.activity_type == ActivityType.FOOD
            ]
            confirmed_or_flagged = (
                not food
                or "DIETARY_UNVERIFIED" in codes
                or all(
                    any(
                        contains_phrase(
                            " ".join(
                                filter(
                                    None,
                                    [
                                        entities[a.place_id].name,
                                        getattr(entities[a.place_id], "cuisine", None),
                                        getattr(entities[a.place_id], "dietary_notes", None),
                                    ],
                                )
                            ),
                            d.value.replace("_", " "),
                        )
                        for d in req.preferences.dietary
                    )
                    for a in food
                )
            )
            results.append((confirmed_or_flagged, "dietary needs neither confirmed nor flagged"))
        return _checks(results)


class ResearchTraceabilityMetric(BaseMetric):
    """Research-level grounding (used on /research responses): every entity cites a returned
    search result whose text contains its name, and every kept price quote is in that text."""

    metric_name = "research_traceability"
    kind = "deterministic"

    def __init__(self, threshold_value: float | None = None):
        self.threshold = threshold(self.metric_name) if threshold_value is None else threshold_value
        self.score = self.reason = self.success = self.error = None
        self.include_reason, self.async_mode, self.strict_mode, self.verbose_mode = True, False, False, False

    @property
    def __name__(self) -> str:
        return self.metric_name

    def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        from app.schemas import ResearchResponse

        resp = ResearchResponse.model_validate(test_case.metadata["research_response"])
        hits = {h.source_id: h for h in resp.search_results}
        problems, total = [], 0
        for e in resp.research.entity_index().values():
            total += 1
            hit = hits.get(e.source_id)
            if hit is None:
                problems.append(f"{e.id} cites missing source {e.source_id}")
            elif not contains_phrase(f"{hit.title} {hit.content}", e.name):
                problems.append(f"{e.id} '{e.name}' not found in {e.source_id}")
            elif e.price and not contains_phrase(hit.content, e.price.quote):
                problems.append(f"{e.id} price quote not in {e.source_id}")
        self.score = round((total - len(problems)) / total, 4) if total else 0.0
        self.reason = "; ".join(problems) or f"{total}/{total} entities traceable"
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)


def deterministic_metrics() -> list[_DeterministicMetric]:
    return [
        EntityGroundingMetric(),
        UnsupportedPlaceMetric(),
        CompletenessMetric(),
        BudgetConstraintMetric(),
        PreferenceMatchMetric(),
        ConstraintAdherenceMetric(),
    ]
