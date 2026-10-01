"""Evaluation logic: dataset, deterministic DeepEval metrics, report structure.

These run offline. They check that each metric PASSES a correct response and
CATCHES the specific defect it exists for, using deliberately broken copies.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("deepeval")

from app.config import Settings  # noqa: E402
from app.llm.client import StructuredLLM  # noqa: E402
from app.schemas import TravelRequest, TravelResponse  # noqa: E402
from app.services.research_planner import ResearchPlanner  # noqa: E402
from app.services.travel_planner import TravelPlanner  # noqa: E402
from evaluation.dataset import load_cases  # noqa: E402
from evaluation.metrics.deterministic import (  # noqa: E402
    BudgetConstraintMetric,
    CompletenessMetric,
    ConstraintAdherenceMetric,
    EntityGroundingMetric,
    PreferenceMatchMetric,
    ResearchTraceabilityMetric,
    UnsupportedPlaceMetric,
)
from evaluation.metrics.judge import judge_unavailable_reason  # noqa: E402
from evaluation.runner import _settings_for, run  # noqa: E402
from evaluation.testcase_builder import build_test_case  # noqa: E402
from tests.fakes import (  # noqa: E402
    FakeSearchProvider,
    ScriptedChatModel,
    goa_draft_json,
    goa_extraction_json,
    goa_items,
)


def _llm(script):
    return StructuredLLM(
        ScriptedChatModel(script=script), model_name="t", timeout_seconds=5, native_json_schema=False
    )


@pytest.fixture
def goa(make_settings, goa_payload):
    """A correct response for the Goa fixtures (real planner code, faked providers)."""
    request = TravelRequest.model_validate(goa_payload)
    planner = TravelPlanner(
        make_settings(),
        search_provider=FakeSearchProvider(goa_items()),
        research_llm=_llm([json.dumps(goa_extraction_json())]),
        planner_llm=_llm([json.dumps(goa_draft_json())]),
    )
    return request, asyncio.run(planner.run(request, "eval-test"))


def _score(metric, request, response_dict):
    response = TravelResponse.model_validate(response_dict)
    metric.measure(build_test_case("t", request, response))
    return metric


# ---------- dataset ----------
def test_dataset_covers_required_destinations_and_styles():
    cases = load_cases()
    assert len(cases) >= 10
    assert {c.request.destination for c in cases} >= {"Goa", "Hyderabad", "Jaipur", "Delhi", "Bengaluru"}
    styles = {c.request.preferences.travel_style.value for c in cases}
    assert {"couple", "family", "solo", "friends", "business"} <= styles
    assert {c.request.preferences.accommodation.value for c in cases} >= {"hostel", "luxury", "budget"}
    assert all(c.expected_behavior for c in cases)


def test_relative_start_dates_resolve_to_future_dates():
    goa = next(c for c in load_cases() if c.id == "goa_couple_beaches")
    assert goa.request.start_date is not None and goa.request.end_date is not None


def test_unknown_case_id_fails_loudly():
    with pytest.raises(ValueError, match="unknown case"):
        load_cases(only=["atlantis"])


# ---------- deterministic metrics: pass on correct output ----------
@pytest.mark.parametrize(
    "metric_cls",
    [
        EntityGroundingMetric,
        UnsupportedPlaceMetric,
        CompletenessMetric,
        BudgetConstraintMetric,
        ConstraintAdherenceMetric,
    ],
)
def test_correct_response_passes(goa, metric_cls):
    request, response = goa
    metric = _score(metric_cls(), request, response.model_dump(mode="json"))
    assert metric.success, metric.reason


def test_preference_match_on_fixture(goa):
    request, response = goa
    metric = _score(PreferenceMatchMetric(), request, response.model_dump(mode="json"))
    # beaches (Baga Beach), food (seafood dinner), nightlife (Baga's verified description mentions it)
    assert metric.score == 1.0, metric.reason


def test_preference_match_reports_uncovered_interest(goa):
    request, response = goa
    request = request.model_copy(
        update={"preferences": request.preferences.model_copy(update={"interests": ["beaches", "adventure"]})}
    )
    metric = _score(PreferenceMatchMetric(), request, response.model_dump(mode="json"))
    assert metric.score == 0.5 and "not covered ['adventure']" in metric.reason


# ---------- deterministic metrics: catch each defect ----------
def test_grounding_catches_unknown_place(goa):
    request, response = goa
    data = response.model_dump(mode="json")
    data["itinerary"]["days"][0]["activities"][0]["place_id"] = "A99"
    metric = _score(EntityGroundingMetric(), request, data)
    assert not metric.success and "unknown place_id A99" in metric.reason


def test_unsupported_place_catches_invented_venue(goa):
    request, response = goa
    data = response.model_dump(mode="json")
    data["itinerary"]["days"][2]["activities"][0]["description"] = "Then head to Imaginary Palace."
    metric = _score(UnsupportedPlaceMetric(), request, data)
    assert metric.score == 0.0 and "Imaginary Palace" in metric.reason


def test_completeness_catches_missing_day(goa):
    request, response = goa
    data = response.model_dump(mode="json")
    data["itinerary"]["days"].pop()
    assert not _score(CompletenessMetric(), request, data).success


def test_budget_catches_wrong_arithmetic(goa):
    request, response = goa
    data = response.model_dump(mode="json")
    data["budget"]["total"] += 1000
    metric = _score(BudgetConstraintMetric(), request, data)
    assert not metric.success and "lines sum to" in metric.reason


def test_budget_catches_hidden_overrun(goa):
    request, response = goa
    data = response.model_dump(mode="json")
    data["quality"]["issues"] = [i for i in data["quality"]["issues"] if i["code"] != "OVER_BUDGET"]
    if data["budget"]["within_budget"]:
        pytest.skip("fixture plan is within budget")
    assert "no OVER_BUDGET warning" in _score(BudgetConstraintMetric(), request, data).reason


def test_constraints_catch_pace_violation(goa):
    request, response = goa
    data = response.model_dump(mode="json")
    extra = dict(data["itinerary"]["days"][0]["activities"][0], place_id=None, generic_kind="free_time")
    data["itinerary"]["days"][0]["activities"] += [extra] * 3  # 5 > moderate cap of 4
    assert not _score(ConstraintAdherenceMetric(), request, data).success


def test_research_traceability(make_settings, goa_payload):
    planner = ResearchPlanner(
        make_settings(),
        search_provider=FakeSearchProvider(goa_items()),
        llm=_llm([json.dumps(goa_extraction_json())]),
    )
    resp = asyncio.run(planner.run(TravelRequest.model_validate(goa_payload), "r"))
    from deepeval.test_case import LLMTestCase

    tc = LLMTestCase(
        input="x", actual_output="y", metadata={"research_response": resp.model_dump(mode="json")}
    )
    metric = ResearchTraceabilityMetric()
    metric.measure(tc)
    assert metric.success, metric.reason
    broken = resp.model_dump(mode="json")
    broken["research"]["attractions"][1]["price"]["quote"] = "₹9,999 per person"
    metric.measure(LLMTestCase(input="x", actual_output="y", metadata={"research_response": broken}))
    assert not metric.success and "price quote not in" in metric.reason


# ---------- runner and judge gating ----------
def test_runner_demo_report_is_complete_and_labelled(tmp_path):
    report, path = run(
        "demo", use_judge=True, only=["goa_couple_beaches", "delhi_business_one_day"], out_dir=tmp_path
    )
    saved = json.loads(path.read_text())
    assert saved["mode"] == "demo" and saved["mode_notice"].startswith("DEMO EVALUATION")
    assert saved["judge"] == {
        "enabled": False,
        "model": None,
        "status": "NOT RUN: judge disabled in demo mode",
    }
    assert saved["threshold_status"].startswith("INITIAL ENGINEERING THRESHOLDS")
    assert saved["configuration"]["model"] == "demo-model" and saved["timestamp"]
    case = saved["cases"][0]
    assert case["status"] == "evaluated" and case["input"]["destination"] == "Goa"
    assert {"name", "kind", "score", "threshold", "passed", "explanation"} <= set(case["metrics"][0])
    assert saved["summary"]["cases_total"] == 2


def test_live_mode_without_keys_refuses(monkeypatch):
    for var in ("GEMINI_API_KEY", "LLM_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir("/")  # make sure no developer .env is picked up
    with pytest.raises(SystemExit, match="needs"):
        _settings_for("live")


def test_judge_requires_a_key():
    assert judge_unavailable_reason(Settings(_env_file=None)).startswith("NOT RUN")
