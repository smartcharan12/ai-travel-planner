"""Research-only service behind POST /api/v1/research.

Runs the Stage 2 graph (search -> extraction -> grounding) and returns the
verified research without planning. Useful for debugging research quality
on its own; it is also the first half of what /plan does.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.config import Settings
from app.graph.research_graph import build_research_graph
from app.llm.client import StructuredLLM, merge_usage
from app.observability.metrics import metrics
from app.schemas import PlanMetadata, ResearchResponse, TravelRequest
from app.services.common import (
    annotate_request,
    data_notice,
    require_configuration,
    resolve_llm,
    resolve_search,
)
from app.tools.search import SearchProvider

NEXT_STEP = (
    "This endpoint returns verified research only. POST /api/v1/plan uses the same research to build "
    "an itinerary from these entities."
)


class ResearchPlanner:
    def __init__(
        self,
        settings: Settings,
        *,
        search_provider: SearchProvider | None = None,
        llm: StructuredLLM | None = None,
    ):
        # Providers are optional so tests can inject fakes; in production they
        # are built from settings on first use.
        self._settings = settings
        self._search_provider = search_provider
        self._llm = llm

    async def run(self, request: TravelRequest, request_id: str) -> ResearchResponse:
        if self._search_provider is None or self._llm is None:
            require_configuration(self._settings)
        search = resolve_search(self._settings, self._search_provider)
        llm = resolve_llm(self._settings, self._llm, temperature=self._settings.research_temperature)
        graph = build_research_graph(search, llm, self._settings)
        annotate_request(
            request,
            stage="research",
            demo_mode=search.is_demo or llm.is_demo,
            model=llm.model_name,
            search_provider=search.name,
        )

        started = time.perf_counter()
        searched_at = datetime.now(UTC)
        state = await graph.ainvoke({"request": request, "searched_at": searched_at})
        total_ms = (time.perf_counter() - started) * 1000
        metrics.observe_ms("research_workflow_latency", total_ms)

        is_demo = search.is_demo or llm.is_demo
        usage = merge_usage(state["llm_usage"])
        summary = state["search_summary"]
        return ResearchResponse(
            request_id=request_id,
            status="success" if all(s.status == "ok" for s in summary) else "partial",
            data_mode="demo" if is_demo else "live",
            notice=data_notice(is_demo, searched_at, search.name),
            research=state["research"],
            search_summary=summary,
            search_results=state["hits"],
            grounding=state["grounding"],
            warnings=state.get("warnings", []),
            next_step=NEXT_STEP,
            metadata=PlanMetadata(
                model=llm.model_name,
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
