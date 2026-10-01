"""DeepEval suite for research quality on its own (POST /api/v1/research behaviour).

Checks that every verified entity is traceable to the search result it cites.
With EVAL_MODE=live and EVAL_JUDGE=1 it also runs DeepEval's FaithfulnessMetric on the
extracted descriptions against the raw search-result text.
"""

from __future__ import annotations

import asyncio

from deepeval import assert_test
from deepeval.metrics import FaithfulnessMetric
from deepeval.test_case import LLMTestCase

from app.services.research_planner import ResearchPlanner
from evaluation.config import threshold
from evaluation.conftest import USE_JUDGE
from evaluation.metrics.deterministic import ResearchTraceabilityMetric
from evaluation.metrics.judge import judge_unavailable_reason


def test_research_case(case, eval_settings):
    resp = asyncio.run(
        ResearchPlanner(eval_settings).run(case.request, request_id=f"eval-research-{case.id}")
    )
    described = [
        f"{e.name}: {getattr(e, 'description', '') or ''}" for e in resp.research.entity_index().values()
    ]
    test_case = LLMTestCase(
        name=f"research-{case.id}",
        input=f"Research {case.request.destination} for: {', '.join(case.request.preferences.interests)}",
        actual_output="\n".join(described) or "(no entities)",
        retrieval_context=[f"{h.title}: {h.content}" for h in resp.search_results],
        metadata={"research_response": resp.model_dump(mode="json")},
    )
    metrics = [ResearchTraceabilityMetric()]
    if USE_JUDGE and judge_unavailable_reason(eval_settings) is None and not eval_settings.is_demo:
        from deepeval.models import GeminiModel

        from evaluation.metrics.judge import judge_model_name

        judge = GeminiModel(
            model=judge_model_name(eval_settings),
            api_key=eval_settings.llm_api_key.get_secret_value(),
            temperature=0,
        )
        metrics.append(FaithfulnessMetric(threshold=threshold("faithfulness"), model=judge, async_mode=False))
    assert_test(test_case, metrics)
