"""FastAPI application entry point.

Run locally:   uvicorn app.main:app --reload
Interactive API docs (generated from the Pydantic schemas): http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_error_handlers
from app.api.middleware import request_context_middleware
from app.api.routes import router


def create_app() -> FastAPI:
    """Application factory: build a fresh, fully wired app.

    A factory (instead of building the app at import time inside each
    module) lets tests create isolated instances and keeps the wiring of
    middleware, error handlers and routes in one readable place.
    """
    app = FastAPI(
        title="AI Travel Planner",
        version=__version__,
        description="Researched, validated and budgeted travel itineraries.",
    )
    app.middleware("http")(request_context_middleware)
    register_error_handlers(app)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": "ai-travel-planner", "docs": "/docs", "health": "/api/v1/health"}

    return app


app = create_app()
