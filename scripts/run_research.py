"""Run the research workflow (or, with --plan, the full planner) from the CLI and print/save the JSON.

Examples:
    .venv/bin/python -m scripts.run_research --demo
    .venv/bin/python -m scripts.run_research --demo --plan                  # full itinerary
    .venv/bin/python -m scripts.run_research --out goa_research.json   # live: needs keys in .env
    .venv/bin/python -m scripts.run_research --destination Jaipur --days 3 --budget 20000 --travelers 2

Useful for learning (inspect each stage's output) and for recording a REAL
Goa run to replace the illustrative examples in docs/11_request_to_research_flow.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import Settings
from app.core.exceptions import TravelPlannerError
from app.schemas import TravelRequest
from app.services.research_planner import ResearchPlanner
from app.services.travel_planner import TravelPlanner


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--destination", default="Goa")
    parser.add_argument("--origin", default="Bengaluru")
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--budget", type=float, default=25000)
    parser.add_argument("--travelers", type=int, default=2)
    parser.add_argument("--style", default="couple")
    parser.add_argument("--interests", default="beaches,food,nightlife")
    parser.add_argument("--demo", action="store_true", help="offline DEMO mode (no keys, invented data)")
    parser.add_argument("--plan", action="store_true", help="run the full planner (itinerary + budget)")
    parser.add_argument("--out", type=Path, help="also write the JSON response to this file")
    args = parser.parse_args()

    settings = Settings(demo_mode=True) if args.demo else Settings()
    request = TravelRequest(
        destination=args.destination,
        origin_city=args.origin,
        num_days=args.days,
        budget=args.budget,
        num_travelers=args.travelers,
        preferences={"travel_style": args.style, "interests": args.interests.split(",")},
    )
    try:
        planner = TravelPlanner(settings) if args.plan else ResearchPlanner(settings)
        response = asyncio.run(planner.run(request, request_id="cli"))
    except TravelPlannerError as exc:
        error = {"error": exc.code, "message": exc.public_message, "details": exc.details}
        print(json.dumps(error, indent=2))
        return 1

    output = response.model_dump_json(indent=2)
    print(output)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"\nsaved to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
