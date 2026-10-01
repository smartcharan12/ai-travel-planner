"""Domain exceptions shared by every layer of the application.

Internal code raises these; ``app/api/errors.py`` turns them into a consistent
JSON error body. Each exception carries:

- ``code``          stable machine-readable string (frontends and dashboards key on it)
- ``http_status``   the status code the API should return
- ``public_message`` safe text for the user. Never put secrets, raw provider
                    responses or stack traces here.

The original low-level exception (e.g. an ``httpx.ReadTimeout``) is kept via
``raise ... from exc`` so it still shows up in server-side logs.
"""

from __future__ import annotations

from typing import Any


class TravelPlannerError(Exception):
    """Base class: anything the API knows how to report cleanly."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    public_message: str = "An unexpected error occurred."

    def __init__(self, public_message: str | None = None, *, details: dict[str, Any] | None = None):
        self.public_message = public_message or self.public_message
        self.details = details or {}
        super().__init__(self.public_message)


# ---------- Configuration ----------
class ConfigurationError(TravelPlannerError):
    """A required setting (usually an API key) is missing or invalid."""

    code = "CONFIGURATION_ERROR"
    http_status = 503
    public_message = "The service is not configured correctly. Contact the operator."


# ---------- External search ----------
class SearchProviderError(TravelPlannerError):
    """The search API returned an error or an unreadable response."""

    code = "SEARCH_PROVIDER_ERROR"
    http_status = 502
    public_message = "The travel search service failed. Please try again shortly."


class SearchTimeoutError(SearchProviderError):
    code = "SEARCH_TIMEOUT"
    http_status = 504
    public_message = "The travel search service took too long to respond."


class NoResearchResultsError(TravelPlannerError):
    """Search returned nothing usable, so we refuse to let the LLM guess."""

    code = "NO_RESEARCH_RESULTS"
    http_status = 422
    public_message = (
        "We could not find reliable current information for this destination. "
        "Check the spelling or try a nearby, better-known place."
    )


# ---------- LLM ----------
class LLMError(TravelPlannerError):
    code = "LLM_ERROR"
    http_status = 502
    public_message = "The AI model failed to respond. Please try again."


class LLMTimeoutError(LLMError):
    code = "LLM_TIMEOUT"
    http_status = 504
    public_message = "The AI model took too long to respond."


class LLMOutputError(LLMError):
    """The model answered, but not in the JSON/schema we asked for."""

    code = "LLM_INVALID_OUTPUT"
    public_message = "The AI model returned an itinerary in an unexpected format."


class ItineraryValidationError(TravelPlannerError):
    """The itinerary still broke hard rules after every repair attempt."""

    code = "ITINERARY_INVALID"
    http_status = 502
    public_message = "We could not produce an itinerary that passed our quality checks."


# ---------- Rate limiting (ours or an upstream provider's) ----------
class RateLimitError(TravelPlannerError):
    code = "RATE_LIMITED"
    http_status = 429
    public_message = "Too many requests. Please wait a moment and try again."


# ---------- Build-stage placeholder ----------
class PlannerNotReadyError(TravelPlannerError):
    """Raised by /plan until the planning workflow is implemented (Stage 2)."""

    code = "PLANNER_NOT_IMPLEMENTED"
    http_status = 501
    public_message = (
        "Request accepted by validation, but the planning workflow is not built yet (arrives in Stage 2)."
    )
