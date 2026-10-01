"""DeepEval suite for full itineraries (POST /api/v1/plan behaviour).

deepeval test run evaluation/test_itinerary.py        # or: pytest evaluation/test_itinerary.py
"""

from __future__ import annotations

import asyncio

from deepeval import assert_test

from app.services.travel_planner import TravelPlanner
from evaluation.conftest import USE_JUDGE
from evaluation.metrics import deterministic_metrics, judge_metrics, judge_unavailable_reason
from evaluation.testcase_builder import build_test_case


def test_itinerary_case(case, eval_settings):
    response = asyncio.run(TravelPlanner(eval_settings).run(case.request, request_id=f"eval-{case.id}"))
    metrics = deterministic_metrics()
    if USE_JUDGE and judge_unavailable_reason(eval_settings) is None and not eval_settings.is_demo:
        metrics += judge_metrics(eval_settings)
    assert_test(build_test_case(case.id, case.request, response), metrics)
