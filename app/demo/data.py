"""Offline DEMO search data, used only when DEMO_MODE=true (or mock/fake providers).

Rules this file follows so demo output can never pass as real travel advice:

- every name starts with "Sample" and every title ends in "(DEMO)";
- every URL uses the reserved ``.invalid`` top-level domain (RFC 2606), which
  can never resolve to a real website;
- every text says "[DEMO DATA, not real]" and every price says "invented demo figure".

The data is templated with the requested destination so the whole pipeline
(queries -> normalization -> extraction -> grounding -> API) runs for any
destination without keys, but nothing in it is a claim about that place.
"""

from __future__ import annotations

import re

from app.schemas import ResearchCategory

DEMO_NOTICE = (
    "DEMO DATA: invented offline sample content for testing the pipeline. "
    "It is NOT real, NOT current and must not be used to plan travel."
)

_C = ResearchCategory

# (title stem, content template). {d} = destination. Kept in one table so the
# demo is easy to read and extend.
_DEMO_RESULTS: dict[ResearchCategory, list[tuple[str, str]]] = {
    _C.DESTINATION: [
        (
            "Sample Travel Guide",
            "[DEMO DATA, not real] Sample Travel Guide for {d}: an invented overview used to test the "
            "planner offline. Demo tip: carry water. Demo tip: check local transport timings yourself.",
        ),
    ],
    _C.ATTRACTIONS: [
        (
            "Sample Beach Promenade",
            "[DEMO DATA, not real] Sample Beach Promenade is an invented example beach in the Demo North "
            "area of {d}. Visitors typically spend about 2 hours here. "
            "Entry fee: ₹50 per person (invented demo figure).",
        ),
        (
            "Sample Heritage Fort",
            "[DEMO DATA, not real] Sample Heritage Fort is an invented example fort in the Demo Central "
            "area of {d}, used to test offline extraction. No real opening hours are known.",
        ),
        (
            "Sample Night Market",
            "[DEMO DATA, not real] Sample Night Market is an invented example evening market in the Demo "
            "North area of {d}, included to test nightlife interests.",
        ),
    ],
    _C.RESTAURANTS: [
        (
            "Sample Coastal Kitchen",
            "[DEMO DATA, not real] Sample Coastal Kitchen is an invented seafood restaurant in the Demo "
            "North area of {d}. Meal for two: ₹1,200 (invented demo figure).",
        ),
        (
            "Sample Green Thali House",
            "[DEMO DATA, not real] Sample Green Thali House is an invented vegetarian restaurant in the "
            "Demo Central area of {d}, used to test dietary preferences.",
        ),
    ],
    _C.HOTELS: [
        (
            "Sample Mid-range Stay",
            "[DEMO DATA, not real] Sample Mid-range Stay is an invented hotel in the Demo North area of {d}. "
            "Rooms from ₹3,500 per night (invented demo figure).",
        ),
        (
            "Sample Budget Guesthouse",
            "[DEMO DATA, not real] Sample Budget Guesthouse is an invented guesthouse in the Demo Central "
            "area of {d}. No price information is given in this demo source.",
        ),
    ],
    _C.TRANSPORTATION: [
        (
            "Sample Intercity Train",
            "[DEMO DATA, not real] Sample Intercity Train is an invented train service to {d}. "
            "Journey takes about 12 hours in this demo. Fare: ₹900 per person (invented demo figure).",
        ),
        (
            "Sample Scooter Rental",
            "[DEMO DATA, not real] Sample Scooter Rental is an invented local transport option in {d}. "
            "Rental: ₹400 per day (invented demo figure).",
        ),
    ],
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "destination"


def demo_results(destination: str, category: ResearchCategory) -> list[dict[str, str]]:
    """Return raw-ish demo results (title/url/content) for one category."""
    slug = _slug(destination)
    return [
        {
            "title": f"{stem} — {destination} (DEMO)",
            "url": f"https://demo.invalid/{slug}/{category.value}/{index}",
            "content": template.format(d=destination),
        }
        for index, (stem, template) in enumerate(_DEMO_RESULTS[category], start=1)
    ]
