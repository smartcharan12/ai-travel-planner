"""The Stage 2 LangGraph workflow: request -> live search -> typed, verified research.

    START
      -> prepare_queries                      (deterministic)
      -> search_destination | search_attractions | search_restaurants
         | search_hotels | search_transportation   (5 searches IN PARALLEL)
      -> aggregate_research                   (normalize, dedupe, number S1..Sn; stop if nothing usable)
      -> extract_entities                     (Gemini, structured output)
      -> ground_entities                      (deterministic verification against sources)
    END

Why LangGraph instead of plain function calls: it gives us parallel fan-out
and fan-in, one typed state, and a graph we can extend: ``planning_graph.py``
reuses these nodes via ``add_research_nodes`` and attaches the itinerary steps.

Dependencies (search provider, LLM, settings) are passed in, not imported,
so tests can run the real graph with fake providers.
"""

from __future__ import annotations

import logging
import time

from langgraph.graph import END, START, StateGraph

from app.config import Settings
from app.core.exceptions import NoResearchResultsError, SearchProviderError, TravelPlannerError
from app.graph.state import ResearchState
from app.llm.client import StructuredLLM
from app.observability.context import current_stats
from app.observability.logging import log_event
from app.observability.metrics import metrics
from app.prompts.research_prompt import build_research_messages
from app.research.grounding import ground_extraction
from app.research.normalizer import CategoryResults, normalize_results
from app.research.queries import build_research_queries
from app.schemas import CategorySearchSummary, ResearchCategory, ResearchExtraction
from app.tools.search import SearchProvider

logger = logging.getLogger(__name__)


def build_research_graph(provider: SearchProvider, llm: StructuredLLM, settings: Settings):
    """Research-only graph (used by POST /api/v1/research)."""
    graph = StateGraph(ResearchState)
    last = add_research_nodes(graph, provider, llm, settings)
    graph.add_edge(last, END)
    return graph.compile()


def add_research_nodes(
    graph: StateGraph, provider: SearchProvider, llm: StructuredLLM, settings: Settings
) -> str:
    """Add the research nodes and edges to ``graph``, starting at START.

    Returns the name of the last research node so a caller can attach more
    steps after it (the planning graph does exactly that).
    """

    # ---------- node: prepare_queries ----------
    def prepare_queries(state: ResearchState) -> dict:
        return {"queries": build_research_queries(state["request"])}

    # ---------- nodes: search_<category> (one per category, run in parallel) ----------
    def make_search_node(category: ResearchCategory):
        async def search_node(state: ResearchState) -> dict:
            query = next(q for q in state["queries"] if q.category == category)
            started = time.perf_counter()
            error: TravelPlannerError | None = None
            items = []
            try:
                items = await provider.search(query, max_results=settings.search_max_results)
            except TravelPlannerError as exc:
                error = exc  # one category failing must not sink the whole request
            except Exception as exc:  # a provider bug: contain it, keep the details server-side
                logger.exception("unexpected search failure category=%s", category.value)
                error = SearchProviderError(details={"provider": provider.name})
                error.__cause__ = exc
            latency_ms = (time.perf_counter() - started) * 1000
            outcome = "error" if error else ("ok" if items else "empty")
            labels = {"provider": provider.name, "category": category.value}
            metrics.increment("search_calls_total", {**labels, "outcome": outcome})
            metrics.observe_ms("search_latency", latency_ms, {"provider": provider.name})
            stats = current_stats()
            if stats is not None:
                stats.search_call_count += 1
            log_event(
                logger,
                "search_call",
                f"{category.value} -> {outcome}",
                level=logging.INFO if error is None else logging.WARNING,
                provider=provider.name,
                category=category.value,
                outcome=outcome,
                error_code=error.code if error else None,
                latency_ms=round(latency_ms, 1),
                result_count=len(items),
                demo_mode=provider.is_demo,
            )
            return {"category_results": [CategoryResults(query, items, latency_ms, error)]}

        return search_node

    # ---------- node: aggregate_research ----------
    def aggregate_research(state: ResearchState) -> dict:
        results: list[CategoryResults] = state["category_results"]
        outcome = normalize_results(
            results,
            provider=provider.name,
            retrieved_at=state["searched_at"],
            max_content_chars=settings.search_max_content_chars,
        )
        summary: list[CategorySearchSummary] = []
        warnings: list[str] = []
        for batch in sorted(results, key=lambda b: list(ResearchCategory).index(b.query.category)):
            category = batch.query.category
            kept = outcome.kept_per_category.get(category, 0)
            status = "failed" if batch.error else ("ok" if kept else "empty")
            if status == "failed":
                warnings.append(
                    f"{category.value} search failed ({batch.error_code}); that category is missing."
                )
            elif status == "empty":
                warnings.append(f"No usable {category.value} results were found.")
            summary.append(
                CategorySearchSummary(
                    category=category,
                    query=batch.query.text,
                    status=status,
                    raw_results=len(batch.items),
                    kept_results=kept,
                    latency_ms=round(batch.latency_ms, 1) if batch.latency_ms is not None else None,
                    error_code=batch.error_code,
                )
            )

        if not outcome.hits:
            failures = [b.error for b in results if b.error]
            if failures and len(failures) == len(results):
                raise failures[0]  # every search failed: report the real cause (timeout, auth, ...)
            # Refuse to continue: with no sources the LLM could only answer from memory.
            raise NoResearchResultsError(details={"destination": state["request"].destination})

        latencies = [b.latency_ms for b in results if b.latency_ms is not None]
        return {
            "hits": outcome.hits,
            "search_summary": summary,
            "search_latency_ms": max(latencies) if latencies else 0.0,  # parallel: wall time = slowest
            "warnings": warnings,
        }

    # ---------- node: extract_entities (the LLM step) ----------
    async def extract_entities(state: ResearchState) -> dict:
        messages = build_research_messages(
            state["request"], state["hits"], max_per_type=settings.max_entities_per_category
        )
        result = await llm.generate(messages, ResearchExtraction, purpose="research_extraction")
        return {"extraction": result.value, "llm_usage": [result.usage]}

    # ---------- node: ground_entities (deterministic verification) ----------
    def ground_entities(state: ResearchState) -> dict:
        new_warnings: list[str] = []
        research, report = ground_extraction(
            state["extraction"],
            state["hits"],
            destination=state["request"].destination,
            searched_at=state["searched_at"],
            max_per_type=settings.max_entities_per_category,
        )
        if report.rejected:
            new_warnings.append(
                f"{len(report.rejected)} extracted item(s) were discarded because they could not be "
                "verified against their cited source."
            )
        if report.prices_removed:
            new_warnings.append(
                f"{len(report.prices_removed)} price(s) were removed because they could not be matched to "
                "the source text (see grounding.prices_removed)."
            )
        all_warnings = [*state.get("warnings", []), *new_warnings]
        research = research.model_copy(update={"warnings": all_warnings})
        metrics.increment("grounding_rejections_total", value=len(report.rejected))
        log_event(
            logger,
            "research_grounded",
            f"{report.accepted}/{report.extracted} extracted entities verified",
            hits=len(state["hits"]),
            extracted=report.extracted,
            accepted=report.accepted,
            rejected=len(report.rejected),
            rejection_reasons=sorted({r.reason for r in report.rejected}),
            prices_removed=len(report.prices_removed),
        )
        return {"research": research, "grounding": report, "warnings": new_warnings}

    graph.add_node("prepare_queries", prepare_queries)
    search_nodes = []
    for category in ResearchCategory:
        node_name = f"search_{category.value}"
        graph.add_node(node_name, make_search_node(category))
        graph.add_edge("prepare_queries", node_name)  # fan-out
        search_nodes.append(node_name)
    graph.add_node("aggregate_research", aggregate_research)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("ground_entities", ground_entities)

    graph.add_edge(START, "prepare_queries")
    graph.add_edge(search_nodes, "aggregate_research")  # fan-in: waits for all five
    graph.add_edge("aggregate_research", "extract_entities")
    graph.add_edge("extract_entities", "ground_entities")
    return "ground_entities"
