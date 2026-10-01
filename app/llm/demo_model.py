"""Offline DEMO chat model: a LangChain chat model that needs no API key.

It reads the rendered research prompt, finds the ``<source>`` blocks produced
from ``app/demo/data.py`` and answers with extraction JSON, exactly the way
the real model is asked to. That way demo mode runs the *same* code path as
production: prompt rendering, JSON parsing, Pydantic validation, grounding.

For itinerary prompts it builds a simple deterministic plan from the
ALLOWED PLACES list (see ``demo_itinerary``).

It also adds one deliberately invented attraction ("Imaginary Palace") that
no source mentions, so you can watch the grounding step reject it in the
response's ``grounding.rejected`` list.

It is a deterministic parser, not a language model. It understands nothing
except the demo sources.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.prompts.planner_prompt import PLANNER_ROLE, REPAIR_ROLE

_SOURCE_BLOCK = re.compile(
    r'<source id="(?P<id>S\d+)" category="(?P<category>\w+)" domain="[^"]*">\n'
    r"title: (?P<title>.*)\ncontent: (?P<content>.*)\n</source>"
)
_PRICE = re.compile(r"(?P<quote>₹(?P<amount>[\d,]+)(?: (?P<unit>per \w+))?) \(invented demo figure\)")
_AREA = re.compile(r"in the (Demo \w+) area")
_FIRST_SENTENCE = re.compile(r"\[DEMO DATA, not real\] ([^.]*\.)")

HALLUCINATION_NAME = "Imaginary Palace"


def _price(content: str) -> dict[str, Any] | None:
    match = _PRICE.search(content)
    if not match:
        return None
    unit = match["unit"]
    if unit is None and "for two" in content[max(0, match.start() - 25) : match.start()].lower():
        unit = "for two"  # e.g. "Meal for two: ₹1,200"
    return {
        "quote": match["quote"],
        "amount": float(match["amount"].replace(",", "")),
        "currency": "INR",
        "unit": unit,
    }


def _sentence(content: str) -> str:
    match = _FIRST_SENTENCE.search(content)
    return match.group(1) if match else content[:200]


def demo_extraction(prompt_text: str) -> dict[str, Any]:
    """Build extraction JSON from demo source blocks in ``prompt_text``."""
    result: dict[str, Any] = {
        "destination_info": None,
        "attractions": [],
        "restaurants": [],
        "hotels": [],
        "transportation": [],
        "uncertainty_notes": ["Demo mode: no real web sources were consulted; all content is invented."],
    }
    for block in _SOURCE_BLOCK.finditer(prompt_text):
        if not block["title"].endswith("(DEMO)"):
            continue  # never "extract" anything that isn't demo data
        name = block["title"].split(" — ")[0]
        content, sid, category = block["content"], block["id"], block["category"]
        area_match = _AREA.search(content)
        area = area_match.group(1) if area_match else None
        if category == "destination":
            result["destination_info"] = {
                "summary": _sentence(content),
                "best_time_to_visit": None,
                "local_tips": re.findall(r"Demo tip: ([^.]+)\.", content),
                "source_ids": [sid],
            }
        elif category == "attractions":
            result["attractions"].append(
                {
                    "name": name,
                    "source_id": sid,
                    "area": area,
                    "description": _sentence(content),
                    "price": _price(content),
                }
            )
        elif category == "restaurants":
            cuisine = re.search(r"invented (\w+) restaurant", content)
            result["restaurants"].append(
                {
                    "name": name,
                    "source_id": sid,
                    "area": area,
                    "description": _sentence(content),
                    "cuisine": cuisine.group(1) if cuisine else None,
                    "price": _price(content),
                }
            )
        elif category == "hotels":
            kind = re.search(r"invented (\w+) in the", content)
            result["hotels"].append(
                {
                    "name": name,
                    "source_id": sid,
                    "area": area,
                    "description": _sentence(content),
                    "accommodation_type": kind.group(1) if kind else None,
                    "price": _price(content),
                }
            )
        elif category == "transportation":
            result["transportation"].append(
                {
                    "name": name,
                    "source_id": sid,
                    "area": area,
                    "description": _sentence(content),
                    "mode": "train" if "Train" in name else "scooter rental",
                    "scope": "intercity" if "Intercity" in name else "local",
                    "price": _price(content),
                }
            )

    if result["attractions"]:
        # Deliberate hallucination: cites a real demo source that never mentions it.
        result["attractions"].append(
            {
                "name": HALLUCINATION_NAME,
                "source_id": result["attractions"][0]["source_id"],
                "area": None,
                "description": "Deliberately invented by the demo model to show grounding rejecting it.",
                "price": None,
            }
        )
    return result


_PLACE_LINE = re.compile(r"^(?P<id>[ARHT]\d+) \| (?P<type>[a-z ]+?) \| (?P<name>[^|]+?) \|", re.MULTILINE)
_DAYS = re.compile(r"- Duration: (\d+) days")
_MAX_PER_DAY = re.compile(r"At most (\d+) activities per day")

PLANTED_BAD_ID = "A99"


def demo_itinerary(system_text: str, prompt_text: str, *, repair: bool) -> dict[str, Any]:
    """Deterministic draft from the ALLOWED PLACES list.

    The first (non-repair) draft deliberately references an id that does not
    exist ("A99"), so demo mode shows the validator -> repair loop working.
    """
    places = [m.groupdict() for m in _PLACE_LINE.finditer(prompt_text)]
    attractions = [p for p in places if p["type"] == "attraction"]
    restaurants = [p for p in places if p["type"] == "restaurant"]
    hotels = [p for p in places if p["type"] == "hotel"]
    num_days = int(_DAYS.search(prompt_text).group(1))
    cap = int(_MAX_PER_DAY.search(system_text).group(1))

    days = []
    next_attraction = 0
    for day in range(1, num_days + 1):
        acts: list[dict[str, Any]] = []
        for slot in ("morning", "afternoon"):
            if next_attraction < len(attractions):
                place = attractions[next_attraction]
                next_attraction += 1
                acts.append(
                    {
                        "slot": slot,
                        "activity_type": "sightseeing",
                        "place_id": place["id"],
                        "description": "Demo activity (invented data).",
                    }
                )
            else:
                acts.append(
                    {
                        "slot": slot,
                        "activity_type": "leisure",
                        "generic_kind": "free_time",
                        "description": "Generic demo activity.",
                    }
                )
        if restaurants:
            place = restaurants[(day - 1) % len(restaurants)]
            acts.append(
                {
                    "slot": "evening",
                    "activity_type": "food",
                    "place_id": place["id"],
                    "description": "Demo meal (invented data).",
                }
            )
        days.append({"day_number": day, "theme": f"Demo day {day}", "activities": acts[:cap]})

    if not repair and days:
        days[0]["activities"][0]["place_id"] = PLANTED_BAD_ID  # deliberate error for the validator

    return {
        "title": "DEMO itinerary (invented data)",
        "summary": "Offline demo plan built from invented sample places. Not real travel advice.",
        "hotel_id": hotels[0]["id"] if hotels else None,
        "days": days,
        "recommendations": ["Demo mode: replace with live research before travelling."],
        "travel_tips": ["Demo tip: verify everything with real sources."],
        "uncertainty_notes": ["All places and prices in demo mode are invented."],
    }


class DemoChatModel(BaseChatModel):
    """LangChain-compatible stand-in used only in DEMO mode.

    Routes on the system prompt's role line: research extraction, itinerary
    planning, or itinerary repair.
    """

    @property
    def _llm_type(self) -> str:
        return "demo"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        system_text = next((m.text for m in messages if isinstance(m, SystemMessage)), "")
        # The first human message holds the data; later ones would be retry feedback.
        prompt_text = next((m.text for m in messages if isinstance(m, HumanMessage)), "")
        if REPAIR_ROLE in system_text:
            payload = demo_itinerary(system_text, prompt_text, repair=True)
        elif PLANNER_ROLE in system_text:
            payload = demo_itinerary(system_text, prompt_text, repair=False)
        else:
            payload = demo_extraction(prompt_text)
        content = json.dumps(payload, ensure_ascii=False)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])
