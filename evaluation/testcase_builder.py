"""Turn a planner response into a DeepEval ``LLMTestCase``.

DeepEval's test case has text fields meant for LLM judges:

- ``input``              what the user asked (rendered from the TravelRequest)
- ``actual_output``      what the system answered (the itinerary rendered as text)
- ``retrieval_context``  the evidence the answer was supposed to be based on
                         (verified research entities and destination overview)

and a ``metadata`` dict, where we keep the full structured request/response
so deterministic metrics can check exact facts (ids, numbers, day counts)
instead of re-reading text.
"""

from __future__ import annotations

from deepeval.test_case import LLMTestCase

from app.planning.pricing import format_money
from app.schemas import TravelRequest, TravelResponse


def render_input(req: TravelRequest) -> str:
    p = req.preferences
    parts = [
        f"Plan a {req.num_days}-day {p.travel_style.value} trip to {req.destination}",
        f"for {req.num_travelers} traveller(s)",
        f"from {req.origin_city}" if req.origin_city else "",
        f"with a total budget of {format_money(req.budget, req.currency)}.",
        f"Interests: {', '.join(p.interests)}. Pace: {p.pace.value}. Accommodation: {p.accommodation.value}.",
        f"Dietary needs: {', '.join(d.value for d in p.dietary) or 'none'}.",
    ]
    return " ".join(x for x in parts if x)


def render_itinerary(resp: TravelResponse) -> str:
    it = resp.itinerary
    lines = [it.title, it.summary]
    if it.accommodation:
        lines.append(f"Stay: {it.accommodation.name}")
    for day in it.days:
        lines.append(f"Day {day.day_number}: {day.theme}")
        for a in day.activities:
            lines.append(f"- {a.slot.value}: {a.title}. {a.description}")
    for heading, items in (
        ("Recommendations", it.recommendations),
        ("Tips", it.travel_tips),
        ("Not verified", it.uncertainty_notes),
    ):
        if items:
            lines.append(f"{heading}: " + " ".join(items))
    lines.append(f"Estimated total: {format_money(resp.budget.total, resp.budget.currency)}")
    return "\n".join(lines)


def render_evidence(resp: TravelResponse) -> list[str]:
    r = resp.research
    facts: list[str] = []
    if r.destination_info:
        facts.append(
            f"{r.destination_info.name}: {r.destination_info.summary} "
            + " ".join(r.destination_info.local_tips)
        )
    for e in r.entity_index().values():
        desc = getattr(e, "description", None) or ""
        price = getattr(e, "price", None)
        price_text = f"Price: {price.quote}" if price else ""
        facts.append(f"{e.name} ({e.area or 'area unknown'}): {desc} {price_text}".strip())
    return facts


def build_test_case(case_id: str, request: TravelRequest, response: TravelResponse) -> LLMTestCase:
    return LLMTestCase(
        name=case_id,
        input=render_input(request),
        actual_output=render_itinerary(response),
        retrieval_context=render_evidence(response),
        metadata={
            "request": request.model_dump(mode="json"),
            "response": response.model_dump(mode="json"),
        },
    )
