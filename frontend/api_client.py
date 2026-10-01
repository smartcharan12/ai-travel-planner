"""HTTP client for the planner API, used by the Streamlit app.

The frontend never imports backend code: it talks to the API exactly like
any other client would (curl, a mobile app, DeepEval scripts). That keeps
the two deployable separately (two containers in Stage 4/5).
"""

from __future__ import annotations

from typing import Any

import httpx

# Research + 2–3 LLM calls typically take 20–60 s; leave headroom.
DEFAULT_TIMEOUT_SECONDS = 180.0


class PlannerAPIError(Exception):
    """A failure the UI can show: a stable code, a human message, and the request id for support."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id
        self.details = details or {}


def plan_trip(
    base_url: str,
    payload: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """POST the trip to /api/v1/plan and return the TravelResponse JSON, or raise PlannerAPIError."""
    url = f"{base_url.rstrip('/')}/api/v1/plan"
    http = client or httpx.Client(timeout=timeout)
    try:
        response = http.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise PlannerAPIError(
            "CLIENT_TIMEOUT", f"The planner did not answer within {timeout:.0f} seconds. Please try again."
        ) from exc
    except httpx.HTTPError as exc:
        raise PlannerAPIError(
            "API_UNREACHABLE", f"Cannot reach the planner API at {base_url}. Is the backend running?"
        ) from exc
    finally:
        if client is None:
            http.close()

    if response.status_code == 200:
        return response.json()
    try:
        error = response.json()["error"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PlannerAPIError(
            "UNEXPECTED_RESPONSE",
            f"The API answered with HTTP {response.status_code}.",
            status=response.status_code,
        ) from exc
    raise PlannerAPIError(
        error.get("code", "UNKNOWN_ERROR"),
        error.get("message", "Request failed."),
        status=response.status_code,
        request_id=error.get("request_id"),
        details=error.get("details") or {},
    )
