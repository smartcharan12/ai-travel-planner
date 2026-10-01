"""Pure functions that turn form input into a request and a response into display rows.

Kept separate from ``app.py`` so they can be unit-tested without running Streamlit.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

SLOT_LABELS = {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening"}
BASIS_LABELS = {
    "source": "from source",
    "estimate": "estimate",
    "unknown": "price unknown",
}
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~])")


def md_escape(text: str) -> str:
    """Escape Markdown so text written by the LLM or a web page renders literally.

    Without this, a description containing ``[click](http://evil)`` would become a link.
    """
    return _MD_SPECIAL.sub(r"\\\1", text)


def money(amount: float | None, currency: str) -> str:
    if amount is None:
        return "—"
    symbol = "₹" if currency == "INR" else f"{currency} "
    sign = "−" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.0f}"


def build_payload(
    *,
    destination: str,
    origin_city: str,
    num_days: int,
    start_date: date | None,
    budget: float,
    currency: str,
    num_travelers: int,
    travel_style: str,
    pace: str,
    interests: list[str],
    extra_interests: str,
    dietary: list[str],
    transport: list[str],
    accommodation: str,
    special_requirements: str,
) -> dict[str, Any]:
    """Build the JSON body for POST /api/v1/plan. The API does the real validation."""
    all_interests = list(interests) + [i.strip() for i in extra_interests.split(",") if i.strip()]
    payload: dict[str, Any] = {
        "destination": destination.strip(),
        "num_days": int(num_days),
        "budget": float(budget),
        "currency": currency,
        "num_travelers": int(num_travelers),
        "preferences": {
            "travel_style": travel_style,
            "pace": pace,
            "interests": all_interests or ["sightseeing"],
            "dietary": list(dietary),
            "transport": list(transport) or ["any"],
            "accommodation": accommodation,
            "special_requirements": special_requirements.strip() or None,
        },
    }
    if origin_city.strip():
        payload["origin_city"] = origin_city.strip()
    if start_date is not None:
        payload["start_date"] = start_date.isoformat()
    return payload


def entity_index(research: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = ("attractions", "restaurants", "hotels", "transportation")
    return {e["id"]: e for g in groups for e in research.get(g, [])}


def source_urls(response: dict[str, Any]) -> dict[str, str]:
    return {s["id"]: s["url"] for s in response.get("sources", [])}


def activity_line(activity: dict[str, Any], entities: dict[str, dict[str, Any]], currency: str) -> str:
    """One Markdown line per activity: slot, title, place (with source id), cost and its basis."""
    parts = [f"**{SLOT_LABELS[activity['slot']]}** · {md_escape(activity['title'])}"]
    entity = entities.get(activity.get("place_id") or "")
    if entity:
        area = f", {md_escape(entity['area'])}" if entity.get("area") else ""
        parts.append(f"📍 {md_escape(entity['name'])}{area} `{entity['source_id']}`")
    if activity.get("estimated_cost") is not None:
        parts.append(
            f"{money(activity['estimated_cost'], currency)} ({BASIS_LABELS[activity['cost_basis']]})"
        )
    return " — ".join(parts)


def budget_rows(budget: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Category": item["category"].replace("_", " ").capitalize(),
            "Amount": money(item["amount"], budget["currency"]),
            "Basis": BASIS_LABELS[item["basis"]],
            "How it was calculated": item["detail"],
        }
        for item in budget.get("items", [])
    ]


def place_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    urls = source_urls(response)
    rows = []
    for entity in entity_index(response["research"]).values():
        price = entity.get("price")
        rows.append(
            {
                "Id": entity["id"],
                "Name": entity["name"],
                "Area": entity.get("area") or "",
                "Price (as quoted)": price["quote"] if price else "unknown",
                "Source": entity["source_id"],
                "URL": urls.get(entity["source_id"], ""),
            }
        )
    return rows


def source_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"Id": s["id"], "Title": s["title"], "URL": s["url"]} for s in response.get("sources", [])]
