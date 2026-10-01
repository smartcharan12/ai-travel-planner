"""Planning rules shared by the prompt, the optimizer and the validator.

Keeping them in one place guarantees the LLM is *told* the same limits the
code *enforces*.
"""

from __future__ import annotations

import math

from app.schemas import Pace, TimeSlot

# Maximum activities per day, by pace. Meals count as activities: a "moderate"
# day is e.g. sightseeing + lunch + sightseeing + dinner.
MAX_ACTIVITIES_BY_PACE: dict[Pace, int] = {
    Pace.RELAXED: 3,
    Pace.MODERATE: 4,
    Pace.PACKED: 5,
}

# Two things per slot is already a busy morning; three is unrealistic without
# knowing travel times.
MAX_PER_SLOT = 2

# More distinct areas than this in one day suggests zig-zagging across the region.
MAX_AREAS_PER_DAY = 2

SLOT_ORDER: dict[TimeSlot, int] = {TimeSlot.MORNING: 0, TimeSlot.AFTERNOON: 1, TimeSlot.EVENING: 2}


def rooms_needed(travelers: int) -> int:
    """Assume double occupancy: 1–2 travellers → 1 room, 3–4 → 2 rooms, ..."""
    return math.ceil(travelers / 2)


def nights_for(num_days: int) -> int:
    """A 4-day trip has 3 nights. A 1-day trip has none."""
    return max(num_days - 1, 0)
