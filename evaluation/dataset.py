"""Load evaluation cases and turn them into validated TravelRequests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.schemas import TravelRequest
from evaluation.config import DATASET_PATH


@dataclass(frozen=True)
class EvalCase:
    id: str
    description: str
    request: TravelRequest
    expected_behavior: str
    tags: list[str] = field(default_factory=list)


def _to_request(raw: dict[str, Any], today: date) -> TravelRequest:
    data = dict(raw)
    offset = data.pop("start_in_days", None)
    if offset is not None:
        data["start_date"] = (today + timedelta(days=offset)).isoformat()
    return TravelRequest.model_validate(data)


def load_cases(
    path: Path = DATASET_PATH, *, only: list[str] | None = None, today: date | None = None
) -> list[EvalCase]:
    """Load and validate every case. An invalid case fails loudly rather than being skipped."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    today = today or date.today()
    cases = [
        EvalCase(
            id=c["id"],
            description=c["description"],
            request=_to_request(c["request"], today),
            expected_behavior=c["expected_behavior"],
            tags=c.get("tags", []),
        )
        for c in payload["cases"]
    ]
    if only:
        unknown = set(only) - {c.id for c in cases}
        if unknown:
            raise ValueError(f"unknown case id(s): {sorted(unknown)}")
        cases = [c for c in cases if c.id in only]
    return cases
