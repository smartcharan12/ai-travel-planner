"""Evaluation configuration: thresholds, judge model, output location.

THRESHOLD STATUS: INITIAL ENGINEERING THRESHOLDS.
These numbers were chosen by the developer as reasonable starting points.
They are NOT derived from a validated benchmark and NOT scientifically
calibrated. Tune them once a larger dataset of real (live) runs, ideally with
human ratings, shows where good and bad itineraries actually score.

Hard rules use 1.0 on purpose: a deterministic check either holds or it doesn't
(a plan with one invented place is not "90% fine"). Judge-based scores use
softer thresholds because LLM judges are noisy (see docs/19_deepeval.md).

Any threshold can be overridden with an env var, e.g. EVAL_THRESHOLD_PREFERENCE_MATCH=0.5.
"""

from __future__ import annotations

import os
from pathlib import Path

THRESHOLD_STATUS = "INITIAL ENGINEERING THRESHOLDS: not validated; tune on a larger evaluation dataset"

_DEFAULT_THRESHOLDS: dict[str, float] = {
    # deterministic (code) metrics
    "entity_grounding": 1.0,
    "unsupported_places": 1.0,
    "completeness": 1.0,
    "budget_constraint": 1.0,
    "constraint_adherence": 1.0,
    "preference_match": 0.6,
    "research_traceability": 1.0,
    # LLM-as-judge metrics (only run with --judge and a key)
    "faithfulness": 0.7,
    "itinerary_coherence": 0.6,
    "preference_alignment": 0.6,
    "usefulness": 0.6,
}


def threshold(name: str) -> float:
    override = os.getenv(f"EVAL_THRESHOLD_{name.upper()}")
    return float(override) if override else _DEFAULT_THRESHOLDS[name]


def all_thresholds() -> dict[str, float]:
    return {name: threshold(name) for name in _DEFAULT_THRESHOLDS}


ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "datasets" / "travel_cases.json"
RESULTS_DIR = ROOT / "results"

# Judge model: defaults to the app's model. Judging a model with itself risks
# self-preference bias; set EVAL_JUDGE_MODEL to a different model where possible.
JUDGE_MODEL_ENV = "EVAL_JUDGE_MODEL"
