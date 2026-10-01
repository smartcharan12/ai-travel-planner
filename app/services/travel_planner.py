"""The service behind POST /api/v1/plan: research + itinerary + budget.

Uses two StructuredLLM instances on purpose:
- research extraction at RESEARCH_TEMPERATURE (0.0): copy facts, no creativity;
- itinerary planning at LLM_TEMPERATURE (0.3): a little variety in how days are arranged.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.config import Settings
from app.graph.planning_graph import build_planning_graph
from app.llm.client import StructuredLLM, merge_usage
from app.observability.context import current_stats
from app.observability.logging import log_event
from app.observability.metrics import metrics
from app.schemas import PlanMetadata, TravelRequest, TravelResponse
from app.services.common import (
    annotate_request,
    data_notice,
    require_configuration,
    resolve_llm,
    resolve_search,
)
from app.tools.search import SearchProvider

logger = logging.getLogger(__name__)


class TravelPlanner:
    def __init__(
        self,
        settings: Settings,
        *,
        search_provider: SearchProvider | None = None,
        research_llm: StructuredLLM | None = None,
        planner_llm: StructuredLLM | None = None,
    ):
        self._settings = settings
        self._search_provider = search_provider
        self._research_llm = research_llm
        self._planner_llm = planner_llm

    async def run(self, request: TravelRequest, request_id: str) -> TravelResponse:
        s = self._settings
        if None in (self._search_provider, self._research_llm, self._planner_llm):
            require_configuration(s)
        search = resolve_search(s, self._search_provider)
        research_llm = resolve_llm(s, self._research_llm, temperature=s.research_temperature)
        planner_llm = resolve_llm(s, self._planner_llm, temperature=s.llm_temperature)
        graph = build_planning_graph(search, research_llm, planner_llm, s)
        is_demo = search.is_demo or research_llm.is_demo or planner_llm.is_demo
        annotate_request(
            request,
            stage="itinerary",
            demo_mode=is_demo,
            model=planner_llm.model_name,
            search_provider=search.name,
        )

        started = time.perf_counter()
        searched_at = datetime.now(UTC)
        state = await graph.ainvoke({"request": request, "searched_at": searched_at})
        total_ms = (time.perf_counter() - started) * 1000
        metrics.observe_ms("plan_workflow_latency", total_ms)

        usage = merge_usage(state["llm_usage"])
        quality, budget = state["quality"], state["budget"]
        stats = current_stats()
        if stats is not None:
            stats.repair_attempts = quality.repair_attempts
        log_event(
            logger,
            "plan_completed",
            f"{request.num_days}-day plan for {request.destination}",
            destination=request.destination,
            num_days=request.num_days,
            num_travelers=request.num_travelers,
            travel_style=request.preferences.travel_style.value,
            demo_mode=is_demo,
            model=planner_llm.model_name,
            search_provider=search.name,
            llm_calls=usage.calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            repair_attempts=quality.repair_attempts,
            final_validation="passed",
            grounded_activity_ratio=quality.grounded_activity_ratio,
            within_budget=budget.within_budget,
            budget_complete=budget.complete,
            search_latency_ms=round(state["search_latency_ms"], 1),
            llm_latency_ms=round(usage.latency_ms, 1),
            total_latency_ms=round(total_ms, 1),
        )
        summary = state["search_summary"]
        research = state["research"]
        return TravelResponse(
            request_id=request_id,
            status="success" if all(c.status == "ok" for c in summary) else "partial",
            data_mode="demo" if is_demo else "live",
            notice=data_notice(is_demo, searched_at, search.name),
            itinerary=state["itinerary"],
            budget=state["budget"],
            research=research,
            sources=research.sources,
            search_summary=summary,
            grounding=state["grounding"],
            warnings=state.get("warnings", []),
            quality=state["quality"],
            metadata=PlanMetadata(
                model=planner_llm.model_name,
                search_provider=search.name,
                llm_calls=usage.calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                search_latency_ms=round(state["search_latency_ms"], 1),
                llm_latency_ms=round(usage.latency_ms, 1),
                total_latency_ms=round(total_ms, 1),
                is_demo=is_demo,
            ),
        )
