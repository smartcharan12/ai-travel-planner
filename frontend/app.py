"""Streamlit UI for the AI Travel Planner.

Run (with the API already running on :8000):
    API_BASE_URL=http://localhost:8000 .venv/bin/streamlit run frontend/app.py

Streamlit re-runs this whole script on every interaction. The last result is
kept in ``st.session_state`` so switching tabs doesn't call the API again.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

# `streamlit run frontend/app.py` puts frontend/ (not the repo root) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontend import api_client  # noqa: E402
from frontend.presenters import (  # noqa: E402
    activity_line,
    budget_rows,
    build_payload,
    entity_index,
    md_escape,
    money,
    place_rows,
    source_rows,
)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

INTERESTS = [
    "beaches",
    "food",
    "nightlife",
    "history",
    "nature",
    "shopping",
    "adventure",
    "culture",
    "relaxation",
]
STYLES = ["solo", "couple", "family", "friends", "business"]
PACES = ["relaxed", "moderate", "packed"]
DIETS = ["vegetarian", "vegan", "jain", "halal", "gluten_free", "no_seafood"]
TRANSPORT = ["any", "flight", "train", "bus", "car"]
STAYS = ["mid_range", "budget", "hostel", "homestay", "luxury", "any"]
CURRENCIES = ["INR", "USD", "EUR", "GBP"]


def render_form() -> dict | None:
    with st.form("trip"):
        left, right = st.columns(2)
        destination = left.text_input("Destination *", value="Goa")
        origin_city = right.text_input("Starting city", value="Bengaluru")
        num_days = left.number_input("Number of days", min_value=1, max_value=14, value=4)
        use_dates = right.checkbox("I know my start date")
        start = right.date_input(
            "Start date", value=date.today() + timedelta(days=30), min_value=date.today()
        )
        budget = left.number_input("Total budget (all travellers)", min_value=1.0, value=25000.0, step=1000.0)
        currency = right.selectbox("Currency", CURRENCIES)
        num_travelers = left.number_input("Travellers", min_value=1, max_value=10, value=2)
        travel_style = right.selectbox("Travel style", STYLES, index=1)
        pace = left.selectbox("Pace", PACES, index=1)
        accommodation = right.selectbox("Accommodation", STAYS)
        interests = st.multiselect("Interests", INTERESTS, default=["beaches", "food", "nightlife"])
        extra_interests = st.text_input("Other interests (comma-separated)")
        dietary = st.multiselect("Dietary preferences", DIETS)
        transport = st.multiselect("Transport preferences", TRANSPORT, default=["train"])
        special = st.text_area(
            "Special requirements", max_chars=300, placeholder="e.g. wheelchair accessible"
        )
        submitted = st.form_submit_button("Generate itinerary", type="primary")
    if not submitted:
        return None
    return build_payload(
        destination=destination,
        origin_city=origin_city,
        num_days=num_days,
        start_date=start if use_dates else None,
        budget=budget,
        currency=currency,
        num_travelers=num_travelers,
        travel_style=travel_style,
        pace=pace,
        interests=interests,
        extra_interests=extra_interests,
        dietary=dietary,
        transport=transport,
        accommodation=accommodation,
        special_requirements=special,
    )


def render_error(error: api_client.PlannerAPIError) -> None:
    st.error(error.message)
    fields = error.details.get("fields") if error.details else None
    if fields:
        for f in fields:
            st.write(f"- **{md_escape(f['field'])}**: {md_escape(f['message'])}")
    if error.details.get("missing"):
        st.write("Missing server configuration: " + ", ".join(error.details["missing"]))
    st.caption(
        f"Error code: {error.code}" + (f" · request id: {error.request_id}" if error.request_id else "")
    )


def render_result(result: dict) -> None:
    itinerary, budget, research = result["itinerary"], result["budget"], result["research"]
    currency = budget["currency"]
    if result["data_mode"] == "demo":
        st.warning(result["notice"], icon="⚠️")
    else:
        st.info(result["notice"], icon="ℹ️")
    if result["warnings"]:
        with st.expander(f"{len(result['warnings'])} warning(s) to review", expanded=True):
            for w in result["warnings"]:
                st.write(f"- {md_escape(w)}")

    st.header(md_escape(itinerary["title"]))
    st.write(md_escape(itinerary["summary"]))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Estimated total", money(budget["total"], currency))
    c2.metric("Your budget", money(budget["budget"], currency))
    c3.metric(
        "Remaining",
        money(budget["remaining"], currency),
        delta="within budget" if budget["within_budget"] else "over budget",
        delta_color="normal" if budget["within_budget"] else "inverse",
    )
    c4.metric("Per person", money(budget["per_person_total"], currency))

    schedule, costs, places, quality = st.tabs(["Daily schedule", "Budget", "Places & sources", "Quality"])
    entities = entity_index(research)

    with schedule:
        stay = itinerary.get("accommodation")
        if stay:
            rate = (
                money(stay["nightly_rate"], currency) + "/night" if stay["nightly_rate"] else "rate unknown"
            )
            st.write(f"🏨 **Stay:** {md_escape(stay['name'])} ({md_escape(stay.get('area') or '')}) · {rate}")
        for day in itinerary["days"]:
            label = f"Day {day['day_number']}"
            if day.get("calendar_date"):
                label += f" · {day['calendar_date']}"
            st.subheader(f"{label} · {md_escape(day['theme'])}")
            for activity in day["activities"]:
                st.markdown(activity_line(activity, entities, currency))
                st.caption(md_escape(activity["description"]))
        for heading, key in (
            ("Recommendations", "recommendations"),
            ("Travel tips", "travel_tips"),
            ("Not verified", "uncertainty_notes"),
        ):
            if itinerary.get(key):
                st.markdown(f"**{heading}**")
                for line in itinerary[key]:
                    st.write(f"- {md_escape(line)}")

    with costs:
        st.dataframe(budget_rows(budget), hide_index=True)
        if not budget["complete"]:
            st.warning("Some costs are unknown and counted as 0, so the real total will be higher.")
        st.markdown("**Assumptions**")
        for a in budget["assumptions"]:
            st.write(f"- {md_escape(a)}")

    with places:
        st.caption("Every place below was found in, and checked against, the linked source.")
        link = {"URL": st.column_config.LinkColumn("URL")}
        st.dataframe(place_rows(result), hide_index=True, column_config=link)
        st.markdown("**Sources**")
        st.dataframe(source_rows(result), hide_index=True, column_config=link)

    with quality:
        q, meta = result["quality"], result["metadata"]
        a, b, c = st.columns(3)
        a.metric("Activities at researched places", f"{q['grounded_activity_ratio']:.0%}")
        b.metric("Budget backed by source prices", f"{q['sourced_cost_ratio']:.0%}")
        c.metric("Repair rounds", q["repair_attempts"])
        if q["optimization_notes"]:
            st.markdown("**Optimizer changes**")
            for note in q["optimization_notes"]:
                st.write(f"- {md_escape(note)}")
        rejected = result["grounding"]["rejected"]
        if rejected:
            st.markdown("**Discarded by verification**")
            for r in rejected:
                st.write(f"- {md_escape(r['name'])} ({r['reason']})")
        st.json(meta, expanded=False)


def main() -> None:
    st.set_page_config(page_title="AI Travel Planner", page_icon="🧭", layout="wide")
    st.title("AI Travel Planner")
    st.caption(
        "Itineraries built only from verified web research. Prices appear only when a source states them."
    )

    payload = render_form()
    if payload is not None:
        with st.spinner("Researching live sources and planning your trip. This can take up to a minute…"):
            try:
                st.session_state["result"] = api_client.plan_trip(API_BASE_URL, payload)
                st.session_state.pop("error", None)
            except api_client.PlannerAPIError as exc:
                st.session_state["error"] = exc
                st.session_state.pop("result", None)

    if "error" in st.session_state:
        render_error(st.session_state["error"])
    elif "result" in st.session_state:
        render_result(st.session_state["result"])


main()
