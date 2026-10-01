"""Test doubles for the external services: no test in tests/unit, tests/api or
tests/integration touches the network.

The Goa texts below are HAND-WRITTEN fixtures in Tavily's response format,
written to exercise our code. They are not recorded API responses and are not
travel facts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.schemas import ResearchCategory, ResearchQuery, SearchHit
from app.tools.search.base import SearchProvider, SearchResultItem

C = ResearchCategory

# ---------- Raw Tavily-shaped payloads (hand-written fixtures) ----------
TAVILY_GOA_ATTRACTIONS: dict[str, Any] = {
    "query": "top things to do in Goa for couple travellers interested in beaches, food, nightlife",
    "results": [
        {
            "title": "15 Best Things to Do in Goa",
            "url": "https://www.example-travel.com/goa/things-to-do?utm_source=x",
            "content": "Baga Beach in North Goa is known for water sports and nightlife along Tito's Lane. "
            "Fort Aguada, a 17th-century Portuguese fort near Candolim, offers sea views. "
            "Entry fee: ₹50 per person.",
            "score": 0.91,
            "raw_content": None,
        },
        {
            "title": "Goa beaches guide",
            "url": "https://blog.example.org/goa-beaches",
            "content": "Palolem Beach in South Goa is a calm crescent bay, popular with couples.",
            "score": 0.84,
        },
    ],
    "response_time": 1.2,
}


def tavily_payload(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"query": "q", "results": results, "response_time": 0.5}


# ---------- Provider-neutral items per category ----------
def goa_items() -> dict[ResearchCategory, list[SearchResultItem]]:
    def item(title: str, url: str, content: str) -> SearchResultItem:
        return SearchResultItem(title=title, url=url, content=content, score=0.8)

    return {
        C.DESTINATION: [
            item(
                "Goa travel guide",
                "https://guide.example.com/goa",
                "Goa is best visited between November and February. Rent a scooter to get around.",
            ),
        ],
        C.ATTRACTIONS: [
            item(
                "Best things to do in Goa",
                "https://www.example-travel.com/goa/things-to-do",
                "Baga Beach in North Goa is known for nightlife. Fort Aguada near Candolim is a "
                "17th-century fort. Entry fee: ₹50 per person.",
            ),
        ],
        C.RESTAURANTS: [
            item(
                "Where to eat in Goa",
                "https://food.example.com/goa",
                "Fisherman's Wharf in Cavelossim, Goa serves Goan seafood; "
                "a meal for two costs about ₹1,500.",
            ),
        ],
        C.HOTELS: [
            item(
                "Mid-range hotels in Goa",
                "https://stay.example.com/goa",
                "Example Bay Resort in Calangute, Goa has rooms from ₹4,200 per night.",
            ),
        ],
        C.TRANSPORTATION: [
            item(
                "Bengaluru to Goa",
                "https://transit.example.com/blr-goa",
                "The overnight train from Bengaluru to Goa (Madgaon) takes about 12 hours. "
                "In Goa, scooter rental costs ₹400 per day.",
            ),
        ],
    }


def goa_extraction_json() -> dict[str, Any]:
    """What a well-behaved model would return for goa_items() (S1..S5 in category order)."""
    return {
        "destination_info": {
            "summary": "Goa is best visited between November and February.",
            "best_time_to_visit": "November to February",
            "local_tips": ["Rent a scooter to get around."],
            "source_ids": ["S1"],
        },
        "attractions": [
            {
                "name": "Baga Beach",
                "source_id": "S2",
                "area": "North Goa",
                "description": "Beach known for nightlife.",
                "category": "beach",
            },
            {
                "name": "Fort Aguada",
                "source_id": "S2",
                "area": "Candolim",
                "description": "17th-century fort.",
                "category": "fort",
                "price": {"quote": "₹50 per person", "amount": 50, "currency": "INR", "unit": "per person"},
            },
            # Hallucination: famous place, but S2 never mentions it.
            {"name": "Dudhsagar Falls", "source_id": "S2", "description": "Waterfall."},
        ],
        "restaurants": [
            {
                "name": "Fisherman's Wharf",
                "source_id": "S3",
                "area": "Cavelossim",
                "cuisine": "Goan seafood",
                "price": {"quote": "₹1,500", "amount": 1500, "currency": "INR", "unit": "for two"},
            },
        ],
        "hotels": [
            # Price hallucination: source says ₹4,200, model says 3,000.
            {
                "name": "Example Bay Resort",
                "source_id": "S4",
                "area": "Calangute",
                "price": {
                    "quote": "₹4,200 per night",
                    "amount": 3000,
                    "currency": "INR",
                    "unit": "per night",
                },
            },
        ],
        "transportation": [
            {
                "name": "overnight train",
                "source_id": "S5",
                "mode": "train",
                "scope": "intercity",
                "duration_note": "about 12 hours",
            },
            {
                "name": "scooter rental",
                "source_id": "S5",
                "mode": "scooter rental",
                "scope": "local",
                "price": {"quote": "₹400 per day", "amount": 400, "currency": "INR", "unit": "per day"},
            },
        ],
        "uncertainty_notes": ["No vegetarian-specific restaurants were found in the sources."],
    }


def make_hit(source_id: str, content: str, *, title: str = "Goa page", category=C.ATTRACTIONS) -> SearchHit:
    return SearchHit(
        source_id=source_id,
        category=category,
        query="q",
        title=title,
        url=f"https://example.com/{source_id}",
        domain="example.com",
        content=content,
        provider="test",
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def make_query(category=C.ATTRACTIONS, destination="Goa") -> ResearchQuery:
    return ResearchQuery(
        category=category, destination=destination, text=f"{category.value} in {destination}"
    )


# ---------- Fake search provider ----------
class FakeSearchProvider(SearchProvider):
    """Returns canned items per category, or raises a configured exception."""

    name = "fake-search"

    def __init__(self, responses: dict[ResearchCategory, list[SearchResultItem] | Exception]):
        self.responses = responses
        self.queries: list[ResearchQuery] = []

    async def search(self, query: ResearchQuery, *, max_results: int) -> list[SearchResultItem]:
        self.queries.append(query)
        response = self.responses.get(query.category, [])
        if isinstance(response, Exception):
            raise response
        return response[:max_results]


# ---------- Fake chat models ----------
class ScriptedChatModel(BaseChatModel):
    """Replies with each scripted item in turn: a str (model text) or an Exception (raised)."""

    script: list[Any]
    usage: dict[str, int] | None = None
    received: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        message = (
            AIMessage(content=step, usage_metadata=self.usage) if self.usage else AIMessage(content=step)
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class SlowChatModel(BaseChatModel):
    delay_seconds: float = 5.0

    @property
    def _llm_type(self) -> str:
        return "slow"

    def _generate(self, *args, **kwargs) -> ChatResult:  # pragma: no cover - async path used
        raise NotImplementedError

    async def _agenerate(self, messages: Sequence[BaseMessage], *args, **kwargs) -> ChatResult:
        await asyncio.sleep(self.delay_seconds)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="{}"))])


# ---------- Stage 3: verified research + itinerary drafts ----------
def goa_research():
    """Verified research built by running the REAL grounding code on the fixtures above.

    Result: A1 Baga Beach (North Goa), A2 Fort Aguada (Candolim, ₹50 per person),
    R1 Fisherman's Wharf (₹1,500 for two), H1 Example Bay Resort (price removed),
    T1 overnight train (intercity, no price), T2 scooter rental (local, ₹400 per day).
    """
    from app.research.grounding import ground_extraction
    from app.research.normalizer import CategoryResults, normalize_results
    from app.schemas import ResearchExtraction

    batches = [CategoryResults(make_query(c), items) for c, items in goa_items().items()]
    hits = normalize_results(
        batches, provider="test", retrieved_at=datetime(2026, 10, 1, tzinfo=UTC), max_content_chars=1200
    ).hits
    research, _ = ground_extraction(
        ResearchExtraction.model_validate(goa_extraction_json()),
        hits,
        destination="Goa",
        searched_at=datetime(2026, 10, 1, tzinfo=UTC),
        max_per_type=8,
    )
    return research


def goa_draft_json(num_days: int = 4) -> dict[str, Any]:
    """A valid draft for goa_research(): every rule satisfied."""
    days = [
        {
            "day_number": 1,
            "theme": "North Goa beaches",
            "activities": [
                {
                    "slot": "morning",
                    "activity_type": "sightseeing",
                    "place_id": "A1",
                    "description": "Relax on the beach.",
                },
                {
                    "slot": "evening",
                    "activity_type": "food",
                    "place_id": "R1",
                    "description": "Goan seafood.",
                },
            ],
        },
        {
            "day_number": 2,
            "theme": "Fort and coast",
            "activities": [
                {
                    "slot": "morning",
                    "activity_type": "sightseeing",
                    "place_id": "A2",
                    "description": "Portuguese fort with sea views.",
                },
                {
                    "slot": "afternoon",
                    "activity_type": "transit",
                    "place_id": "T2",
                    "description": "Explore on a rented scooter.",
                },
            ],
        },
    ]
    for n in range(3, num_days + 1):
        days.append(
            {
                "day_number": n,
                "theme": "Free day",
                "activities": [
                    {
                        "slot": "afternoon",
                        "activity_type": "leisure",
                        "generic_kind": "free_time",
                        "description": "Unplanned time at the beach near your hotel.",
                    },
                ],
            }
        )
    return {
        "title": "4 days in Goa",
        "summary": "Beaches, a fort and seafood.",
        "hotel_id": "H1",
        "days": days[:num_days],
        "recommendations": ["Book the train early."],
        "travel_tips": ["Rent a scooter to get around."],
        "uncertainty_notes": [],
    }
