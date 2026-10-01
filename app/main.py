"""FastAPI application entry point.

Run locally:   uvicorn app.main:app --reload
Interactive API docs (generated from the Pydantic schemas): http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_error_handlers
from app.api.limits import ConcurrencyLimiter, SlidingWindowLimiter
from app.api.middleware import request_context_middleware
from app.api.routes import router
from app.config import get_settings
from app.observability.logging import configure_logging


def create_app() -> FastAPI:
    """Application factory: build a fresh, fully wired app.

    A factory (instead of building the app at import time inside each
    module) lets tests create isolated instances and keeps the wiring of
    middleware, error handlers and routes in one readable place.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format, log_file=settings.log_file)
    app = FastAPI(
        title="AI Travel Planner",
        version=__version__,
        description="Researched, validated and budgeted travel itineraries.",
    )
    app.state.rate_limiter = SlidingWindowLimiter()
    app.state.concurrency = ConcurrencyLimiter()
    if settings.cors_allow_origins:
        # Only for browser clients on other origins. Our Streamlit UI calls the API server-side,
        # so CORS stays off unless CORS_ALLOW_ORIGINS lists explicit origins.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
            allow_credentials=False,
        )
    app.middleware("http")(request_context_middleware)
    register_error_handlers(app)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"service": "ai-travel-planner", "docs": "/docs", "health": "/api/v1/health"}

    return app


app = create_app()
