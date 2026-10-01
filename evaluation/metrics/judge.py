"""LLM-as-a-judge metrics (DeepEval G-Eval + Faithfulness), used only for subjective qualities.

An LLM judge reads the request, the itinerary and the evidence, and scores
qualities that have no single correct answer: is the plan coherent? does it
suit a vegetarian family? is it useful? It is a *signal*, not ground truth:

- judge bias / self-preference: a model tends to rate text like its own higher.
  Using the same Gemini model as judge is convenient but biased; set
  EVAL_JUDGE_MODEL to a different model where possible.
- prompt sensitivity: rewording the criteria changes scores.
- non-determinism: re-running gives different scores; compare averages over
  many cases, not single numbers.
- cost: every judged metric is one or more extra LLM calls per case.

Metrics used, and why each one genuinely fits:
- FaithfulnessMetric (DeepEval built-in): splits the itinerary into claims and
  checks each against ``retrieval_context`` (the verified research). This is the
  textual complement to our deterministic name check.
- G-Eval "itinerary_coherence", "preference_alignment", "usefulness":
  custom rubric-based judgements with explicit evaluation steps.
"""

from __future__ import annotations

import os

from deepeval.metrics import BaseMetric, FaithfulnessMetric, GEval
from deepeval.test_case import SingleTurnParams

from app.config import Settings
from evaluation.config import JUDGE_MODEL_ENV, threshold

_IO = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT]


def judge_unavailable_reason(settings: Settings) -> str | None:
    if settings.llm_api_key is None:
        return "NOT RUN: LLM judge requires GEMINI_API_KEY"
    return None


def judge_model_name(settings: Settings) -> str:
    return os.getenv(JUDGE_MODEL_ENV) or settings.llm_model


def judge_metrics(settings: Settings) -> list[BaseMetric]:
    """Build the judge metrics. Call only when ``judge_unavailable_reason`` is None."""
    from deepeval.models import GeminiModel

    judge = GeminiModel(
        model=judge_model_name(settings), api_key=settings.llm_api_key.get_secret_value(), temperature=0
    )
    common = {"model": judge, "async_mode": False}
    return [
        FaithfulnessMetric(threshold=threshold("faithfulness"), include_reason=True, **common),
        GEval(
            name="itinerary_coherence",
            evaluation_params=_IO,
            evaluation_steps=[
                "Check that each day has a clear focus and its activities fit that focus.",
                "Check that activities within a day are in a sensible order (morning, afternoon, evening).",
                "Check that the pace is realistic for the stated pace preference and number of activities.",
                "Penalise contradictions, repeated sights, or days that feel random.",
            ],
            threshold=threshold("itinerary_coherence"),
            **common,
        ),
        GEval(
            name="preference_alignment",
            evaluation_params=_IO,
            evaluation_steps=[
                "List the traveller's stated interests, travel style, dietary needs and pace from the input.",
                "For each, check whether the itinerary addresses it or honestly says it could not.",
                "Penalise activities that clearly conflict with the stated preferences.",
            ],
            threshold=threshold("preference_alignment"),
            **common,
        ),
        GEval(
            name="usefulness",
            evaluation_params=_IO,
            evaluation_steps=[
                "Judge whether a traveller could follow this plan: clear places, times of day, "
                "practical tips.",
                "Reward explicit statements of uncertainty (unverified prices, dietary checks).",
                "Penalise vague filler, marketing language and advice that is not actionable.",
            ],
            threshold=threshold("usefulness"),
            **common,
        ),
    ]
