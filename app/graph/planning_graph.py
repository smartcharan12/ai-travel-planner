"""The full Stage 3 workflow: research (Stage 2 nodes) -> itinerary -> budget.

    [research nodes ... ground_entities]
      -> check_research          (enough verified places to plan?)
      -> generate_itinerary      (Gemini #2: draft from ALLOWED PLACES only)
      -> optimize_itinerary      (deterministic: order, dedupe, caps)
      -> validate_itinerary      (deterministic: hard rules + warnings)
           ├─ errors, attempts left  -> repair_itinerary (Gemini, given the errors) -> optimize_itinerary
           ├─ errors, no attempts    -> give_up  (raises ITINERARY_INVALID)
           └─ no errors              -> assemble_itinerary (dates, areas, verified prices)
      -> calculate_budget        (deterministic)
      -> quality_check           (deterministic)
    END

The validate -> repair -> optimize -> validate cycle is the only loop, and it
is bounded by MAX_REPAIR_ATTEMPTS, so cost and latency stay bounded too.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.config import Settings
from app.core.exceptions import ItineraryValidationError, NoResearchResultsError
from app.graph.research_graph import add_research_nodes
from app.graph.state import PlannerState
from app.llm.client import StructuredLLM
from app.observability.logging import log_event
from app.observability.metrics import metrics
from app.planning.assembler import assemble_itinerary
from app.planning.budget import calculate_budget
from app.planning.optimizer import optimize_draft
from app.planning.quality import build_quality_report
from app.planning.validator import errors_only, validate_draft
from app.prompts.planner_prompt import build_planner_messages, build_repair_messages
from app.schemas import ItineraryDraft
from app.tools.search import SearchProvider

logger = logging.getLogger(__name__)


def build_planning_graph(
    provider: SearchProvider,
    research_llm: StructuredLLM,
    planner_llm: StructuredLLM,
    settings: Settings,
):
    graph = StateGraph(PlannerState)
    last_research_node = add_research_nodes(graph, provider, research_llm, settings)

    def check_research(state: PlannerState) -> dict:
        research = state["research"]
        if not research.attractions and not research.restaurants:
            # Planning from hotels/transport alone would force the model to invent activities.
            raise NoResearchResultsError(
                "Not enough verified places were found to build an itinerary.",
                details={"destination": state["request"].destination},
            )
        return {"repair_attempts": 0}

    async def generate_itinerary(state: PlannerState) -> dict:
        messages = build_planner_messages(state["request"], state["research"])
        result = await planner_llm.generate(messages, ItineraryDraft, purpose="itinerary_planning")
        return {"draft": result.value, "llm_usage": [result.usage]}

    def optimize_itinerary(state: PlannerState) -> dict:
        outcome = optimize_draft(state["draft"], state["research"], state["request"].preferences.pace)
        return {
            "draft": outcome.draft,
            "optimization_notes": outcome.notes,
            "optimization_warnings": outcome.warnings,
        }

    def validate_itinerary(state: PlannerState) -> dict:
        issues = validate_draft(state["draft"], state["research"], state["request"])
        errors = errors_only(issues)
        attempt = state["repair_attempts"]  # 0 = first draft, n = after n repairs
        passed = not errors
        if attempt == 0:
            # Answers "how often does the LLM produce an invalid itinerary?"
            metrics.increment("itinerary_first_draft_total", {"result": "valid" if passed else "invalid"})
        elif passed:
            # Answers "how often does repair fix it?" (with itinerary_invalid_total)
            metrics.increment("repair_success_total")
        for code in sorted({e.code for e in errors}):
            metrics.increment("validation_failures_total", {"code": code})
        log_event(
            logger,
            "itinerary_validated",
            "passed" if passed else f"{len(errors)} error(s)",
            level=logging.INFO if passed else logging.WARNING,
            attempt=attempt,
            passed=passed,
            error_codes=sorted({e.code for e in errors}),
            warning_codes=sorted({i.code for i in issues if i not in errors}),
        )
        return {"issues": [*issues, *state.get("optimization_warnings", [])]}

    def route_after_validation(state: PlannerState) -> str:
        if not errors_only(state["issues"]):
            return "assemble_itinerary"
        if state["repair_attempts"] < settings.max_repair_attempts:
            return "repair_itinerary"
        return "give_up"

    async def repair_itinerary(state: PlannerState) -> dict:
        errors = errors_only(state["issues"])
        metrics.increment("repair_attempts_total")
        log_event(
            logger,
            "itinerary_repair_requested",
            f"repair attempt {state['repair_attempts'] + 1}",
            attempt=state["repair_attempts"] + 1,
            reasons=sorted({e.code for e in errors}),
        )
        messages = build_repair_messages(state["request"], state["research"], state["draft"], errors)
        result = await planner_llm.generate(messages, ItineraryDraft, purpose="itinerary_repair")
        return {
            "draft": result.value,
            "repair_attempts": state["repair_attempts"] + 1,
            "llm_usage": [result.usage],
        }

    def give_up(state: PlannerState) -> dict:
        metrics.increment("itinerary_invalid_total")
        log_event(
            logger,
            "itinerary_invalid",
            "repairs exhausted",
            level=logging.ERROR,
            repair_attempts=state["repair_attempts"],
            error_codes=sorted({i.code for i in errors_only(state["issues"])}),
        )
        raise ItineraryValidationError(
            details={
                "repair_attempts": state["repair_attempts"],
                "errors": [i.code for i in errors_only(state["issues"])],
            }
        )

    def assemble(state: PlannerState) -> dict:
        return {"itinerary": assemble_itinerary(state["draft"], state["research"], state["request"])}

    def budget(state: PlannerState) -> dict:
        breakdown, issues = calculate_budget(state["request"], state["itinerary"], state["research"])
        if not breakdown.within_budget:
            metrics.increment("budget_overflow_total")
        if not breakdown.complete:
            metrics.increment("budget_incomplete_total")
        return {"budget": breakdown, "budget_issues": issues}

    def quality_check(state: PlannerState) -> dict:
        issues = [*state["issues"], *state["budget_issues"]]
        report = build_quality_report(
            state["itinerary"],
            state["budget"],
            issues,
            state["repair_attempts"],
            state.get("optimization_notes", []),
        )
        return {"quality": report, "warnings": [i.message for i in issues]}

    graph.add_node("check_research", check_research)
    graph.add_node("generate_itinerary", generate_itinerary)
    graph.add_node("optimize_itinerary", optimize_itinerary)
    graph.add_node("validate_itinerary", validate_itinerary)
    graph.add_node("repair_itinerary", repair_itinerary)
    graph.add_node("give_up", give_up)
    graph.add_node("assemble_itinerary", assemble)
    graph.add_node("calculate_budget", budget)
    graph.add_node("quality_check", quality_check)

    graph.add_edge(last_research_node, "check_research")
    graph.add_edge("check_research", "generate_itinerary")
    graph.add_edge("generate_itinerary", "optimize_itinerary")
    graph.add_edge("optimize_itinerary", "validate_itinerary")
    graph.add_conditional_edges(
        "validate_itinerary",
        route_after_validation,
        ["repair_itinerary", "give_up", "assemble_itinerary"],
    )
    graph.add_edge("repair_itinerary", "optimize_itinerary")
    graph.add_edge("give_up", END)
    graph.add_edge("assemble_itinerary", "calculate_budget")
    graph.add_edge("calculate_budget", "quality_check")
    graph.add_edge("quality_check", END)
    return graph.compile()
