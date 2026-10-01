"""What the user is allowed to send to POST /api/v1/plan.

Validation here is the first line of defence: bad input is rejected *before*
we spend money on search or LLM calls, and free-text fields are length-capped
and character-restricted to shrink the prompt-injection surface.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from app.schemas.common import StrictModel

MAX_TRIP_DAYS = 14
MAX_TRAVELERS = 10

# Letters (any language), spaces and light punctuation found in real place
# names: "Goa", "São Paulo", "Coeur d'Alene", "Washington, D.C.", "Rio-Grande".
# Anything else ({ } < > ` newlines ...) is rejected, which also stops users
# from smuggling instructions like "Goa. Ignore previous instructions" + code.
_PLACE_PATTERN = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ .,'\-])*$")


class TravelStyle(StrEnum):
    SOLO = "solo"
    COUPLE = "couple"
    FAMILY = "family"
    FRIENDS = "friends"
    BUSINESS = "business"


class Pace(StrEnum):
    """Controls how many activities the optimizer allows per day."""

    RELAXED = "relaxed"
    MODERATE = "moderate"
    PACKED = "packed"


class AccommodationType(StrEnum):
    HOSTEL = "hostel"
    BUDGET = "budget"
    MID_RANGE = "mid_range"
    LUXURY = "luxury"
    HOMESTAY = "homestay"
    ANY = "any"


class TransportMode(StrEnum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"
    CAR = "car"
    ANY = "any"


class DietaryPreference(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    JAIN = "jain"
    HALAL = "halal"
    GLUTEN_FREE = "gluten_free"
    NO_SEAFOOD = "no_seafood"


class TravelPreferences(StrictModel):
    """How the user likes to travel. Enums (not free text) wherever possible:
    they are easy to validate, easy to put into a prompt, and cannot carry
    injected instructions."""

    travel_style: TravelStyle = TravelStyle.SOLO
    pace: Pace = Pace.MODERATE
    interests: list[str] = Field(
        default_factory=lambda: ["sightseeing"],
        min_length=1,
        max_length=8,
        description="Short topics such as 'beaches', 'food', 'history'.",
    )
    dietary: list[DietaryPreference] = Field(default_factory=list)
    transport: list[TransportMode] = Field(default_factory=lambda: [TransportMode.ANY])
    accommodation: AccommodationType = AccommodationType.MID_RANGE
    special_requirements: str | None = Field(
        default=None,
        max_length=300,
        description="Free text, e.g. 'wheelchair accessible'. Treated as data, never as instructions.",
    )

    @field_validator("interests")
    @classmethod
    def _clean_interests(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            item = " ".join(raw.split()).lower()
            if not item:
                continue
            if len(item) > 40 or not _PLACE_PATTERN.match(item):
                raise ValueError(f"interest {raw!r} must be a short word or phrase (letters only)")
            if item not in cleaned:  # de-duplicate, keep order
                cleaned.append(item)
        if not cleaned:
            raise ValueError("at least one interest is required")
        return cleaned

    @field_validator("dietary", "transport")
    @classmethod
    def _dedupe(cls, values: list) -> list:
        return list(dict.fromkeys(values))

    @field_validator("special_requirements")
    @classmethod
    def _single_line(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Collapse newlines/tabs: multi-line text is the classic shape of a
        # prompt-injection payload ("...\n\nSYSTEM: ignore the rules").
        value = " ".join(value.split())
        return value or None


class TravelRequest(StrictModel):
    """The complete planning request (the JSON body of POST /api/v1/plan)."""

    destination: str = Field(min_length=2, max_length=100, examples=["Goa"])
    origin_city: str | None = Field(default=None, min_length=2, max_length=100, examples=["Bengaluru"])
    num_days: int = Field(ge=1, le=MAX_TRIP_DAYS, examples=[4])
    start_date: date | None = Field(default=None, description="Optional. end_date is derived from it.")
    end_date: date | None = None
    budget: float = Field(gt=0, le=100_000_000, description="Total trip budget for all travelers.")
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$", description="ISO 4217 code.")
    num_travelers: int = Field(default=1, ge=1, le=MAX_TRAVELERS)
    preferences: TravelPreferences = Field(default_factory=TravelPreferences)

    @field_validator("destination", "origin_city")
    @classmethod
    def _valid_place(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Check for line breaks BEFORE normalising whitespace; otherwise
        # "Goa\nIgnore previous instructions" would be flattened and pass.
        if any(ch in value for ch in "\n\r\t\v\f"):
            raise ValueError("must be a single line")
        value = " ".join(value.split())
        if not _PLACE_PATTERN.match(value):
            raise ValueError("must contain only letters, spaces and . , ' -")
        return value

    @model_validator(mode="after")
    def _check_dates(self) -> TravelRequest:
        """Make the three date fields agree with each other.

        Rules: start_date cannot be in the past; if end_date is given it must
        match num_days (inclusive); if only start_date is given we derive
        end_date so downstream code can rely on both being present together.
        """
        if self.end_date is not None and self.start_date is None:
            raise ValueError("end_date requires start_date")
        if self.start_date is None:
            return self
        if self.start_date < date.today():
            raise ValueError("start_date cannot be in the past")
        expected_end = self.start_date + timedelta(days=self.num_days - 1)
        if self.end_date is None:
            self.end_date = expected_end
        elif self.end_date != expected_end:
            raise ValueError(
                f"end_date {self.end_date} does not match num_days={self.num_days} "
                f"(expected {expected_end}; both dates are inclusive)"
            )
        return self

    @property
    def budget_per_person_per_day(self) -> float:
        return self.budget / (self.num_travelers * self.num_days)
