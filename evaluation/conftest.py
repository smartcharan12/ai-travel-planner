"""Shared settings for the DeepEval pytest-style suites (evaluation/test_*.py).

    EVAL_MODE=demo  deepeval test run evaluation/test_itinerary.py     (default: demo)
    EVAL_MODE=live  deepeval test run evaluation/test_itinerary.py     (needs keys)
    EVAL_MODE=live EVAL_JUDGE=1 ...                                     (+ LLM judge)

These files live outside tests/ on purpose: the normal `pytest` run must stay
fast, free and offline. Evaluation is run deliberately.
"""

from __future__ import annotations

import os

import pytest

import evaluation  # noqa: F401  (sets DeepEval telemetry opt-out)
from app.config import Settings
from evaluation.dataset import load_cases
from evaluation.runner import _settings_for

EVAL_MODE = os.getenv("EVAL_MODE", "demo")
USE_JUDGE = os.getenv("EVAL_JUDGE") == "1"


@pytest.fixture(scope="session")
def eval_settings() -> Settings:
    return _settings_for(EVAL_MODE)


def pytest_generate_tests(metafunc):
    if "case" in metafunc.fixturenames:
        cases = load_cases()
        metafunc.parametrize("case", cases, ids=[c.id for c in cases])
