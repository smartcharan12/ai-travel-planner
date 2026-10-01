"""Deterministic clean-up of the LLM's itinerary draft.

The LLM is good at choosing and grouping places; it is unreliable at
counting and at remembering what it already scheduled three days ago.
The optimizer applies four simple, explainable rules, in this order:

1. **Order slots**: sort each day's activities morning → afternoon → evening
   (stable, so the model's order within a slot is kept).
2. **No repeat attractions**: an attraction id scheduled on an earlier day is
   removed from later days. Restaurants and transport may repeat (eating at
   a favourite place twice is fine; seeing the same fort twice is not).
3. **Slot cap**: at most ``MAX_PER_SLOT`` activities in one slot.
4. **Pace cap**: at most N activities per day (relaxed 3 / moderate 4 /
   packed 5). Generic activities (no place id) are dropped first, then the
   latest ones.

It also *flags* (does not fix) days that visit more than ``MAX_AREAS_PER_DAY``
distinct areas, a sign of backtracking. We have area names but no
coordinates or travel times, so silently reshuffling days could make things
worse. A warning is the honest output.

Every change is recorded as a human-readable note that the response returns.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.planning.rules import MAX_ACTIVITIES_BY_PACE, MAX_AREAS_PER_DAY, MAX_PER_SLOT, SLOT_ORDER
from app.planning.titles import short_label
from app.research.text import fold
from app.schemas import (
    DraftActivity,
    IssueSeverity,
    ItineraryDraft,
    Pace,
    ResearchResult,
    ValidationIssue,
)


@dataclass
class OptimizationResult:
    draft: ItineraryDraft
    notes: list[str] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)


def _label(activity: DraftActivity, entities: dict) -> str:
    entity = entities.get(activity.place_id) if activity.place_id else None
    return short_label(entity.name if entity else activity.place_id, activity.generic_kind)


def _drop_for_pace(
    activities: list[DraftActivity], cap: int
) -> tuple[list[DraftActivity], list[DraftActivity]]:
    """Remove activities until ``cap`` remain: generic ones first, then from the end."""
    kept = list(activities)
    dropped: list[DraftActivity] = []
    while len(kept) > cap:
        generic = [i for i, a in enumerate(kept) if a.place_id is None]
        index = generic[-1] if generic else len(kept) - 1
        dropped.append(kept.pop(index))
    return kept, dropped


def optimize_draft(draft: ItineraryDraft, research: ResearchResult, pace: Pace) -> OptimizationResult:
    entities = research.entity_index()
    attraction_ids = {a.id for a in research.attractions}
    cap = MAX_ACTIVITIES_BY_PACE[pace]
    first_seen: dict[str, int] = {}
    notes: list[str] = []
    warnings: list[ValidationIssue] = []
    new_days = []

    for day in sorted(draft.days, key=lambda d: d.day_number):
        n = day.day_number
        ordered = sorted(day.activities, key=lambda a: SLOT_ORDER[a.slot])
        if [a.slot for a in ordered] != [a.slot for a in day.activities]:
            notes.append(f"Day {n}: activities re-ordered morning → afternoon → evening.")

        kept: list[DraftActivity] = []
        per_slot: Counter = Counter()
        for activity in ordered:
            pid = activity.place_id
            if pid in attraction_ids:
                if pid in first_seen:
                    notes.append(
                        f"Day {n}: removed repeat visit to {entities[pid].name} ({pid}), "
                        f"already on day {first_seen[pid]}."
                    )
                    continue
                first_seen[pid] = n
            if per_slot[activity.slot] >= MAX_PER_SLOT:
                notes.append(
                    f"Day {n}: removed '{_label(activity, entities)}' "
                    f"({activity.slot.value} slot already full)."
                )
                continue
            per_slot[activity.slot] += 1
            kept.append(activity)

        kept, dropped = _drop_for_pace(kept, cap)
        for activity in dropped:
            notes.append(
                f"Day {n}: removed '{_label(activity, entities)}' "
                f"to respect the {pace.value} pace ({cap}/day)."
            )

        areas = {
            fold(entities[a.place_id].area)
            for a in kept
            if a.place_id in entities and entities[a.place_id].area
        }
        if len(areas) > MAX_AREAS_PER_DAY:
            warnings.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    code="BACKTRACKING_RISK",
                    message=f"Day {n} covers {len(areas)} different areas; expect extra travel time.",
                    day_number=n,
                )
            )
        new_days.append(day.model_copy(update={"activities": kept}))

    return OptimizationResult(
        draft=draft.model_copy(update={"days": new_days}), notes=notes, warnings=warnings
    )
