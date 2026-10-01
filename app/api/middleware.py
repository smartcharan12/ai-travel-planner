"""HTTP middleware: runs around every request, before and after the route.

Responsibilities:
1. give each request a ``request_id`` (reuse a safe incoming X-Request-ID,
   otherwise generate one) so a single plan can be traced across logs
2. create the per-request ``RequestStats`` that the workflow fills in
   (destination, LLM/search call counts, tokens, error code...)
3. measure latency, record metrics, and write ONE ``request_completed``
   JSON log line per request
4. echo the id back in the ``X-Request-ID`` response header so a user can
   quote it in a bug report and we can find the exact log lines
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.observability.context import RequestStats, request_id_var, request_stats_var
from app.observability.logging import log_event
from app.observability.metrics import metrics

logger = logging.getLogger("app.request")

# Only accept short, boring ids from clients; anything else could be used to
# inject fake lines into our logs.
_SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
# Polling endpoints would flood the logs; they are still counted in metrics.
_QUIET_ROUTES = {"/api/v1/health", "/api/v1/health/ready", "/api/v1/metrics"}


def _route_template(request: Request) -> str:
    """'/api/v1/plan' rather than a raw path with ids, to keep metric keys bounded."""
    route = request.scope.get("route")
    return getattr(route, "path", "unmatched")


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
    id_token = request_id_var.set(request_id)
    stats = RequestStats(request_id=request_id)
    stats_token = request_stats_var.set(stats)
    request.state.request_id = request_id

    started = time.perf_counter()
    status_code = 500  # if call_next raises, the error handler will answer 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        stats.error_code = stats.error_code or "INTERNAL_ERROR"
        raise
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        route = _route_template(request)
        labels = {"route": route, "method": request.method}
        metrics.increment("http_requests_total", {**labels, "status": str(status_code)})
        metrics.observe_ms("http_request_latency", latency_ms, labels)
        if route not in _QUIET_ROUTES:
            level = (
                logging.ERROR
                if status_code >= 500
                else logging.WARNING
                if status_code >= 400
                else logging.INFO
            )
            log_event(
                logger,
                "request_completed",
                f"{request.method} {route} -> {status_code}",
                level=level,
                route=route,
                method=request.method,
                status=status_code,
                latency_ms=round(latency_ms, 1),
                **stats.as_log_fields(),
            )
        request_stats_var.reset(stats_token)
        request_id_var.reset(id_token)
