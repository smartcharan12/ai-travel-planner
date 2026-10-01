"""HTTP middleware: runs around every request, before and after the route.

Responsibilities:
1. give each request a ``request_id`` (reuse a safe incoming X-Request-ID,
   otherwise generate one) so a single plan can be traced across logs
2. measure total latency and record per-route metrics
3. echo the id back in the ``X-Request-ID`` response header so a user can
   quote it in a bug report and we can find the exact log lines
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response

from app.observability.metrics import metrics

# ContextVar = a "global" that is private to the current request, even when
# many requests run concurrently. Logging (Stage 4) reads it automatically.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Only accept short, boring ids from clients; anything else could be used to
# inject fake lines into our logs.
_SAFE_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def _route_template(request: Request) -> str:
    """'/api/v1/plan' rather than a raw path with ids, to keep metric keys bounded."""
    route = request.scope.get("route")
    return getattr(route, "path", "unmatched")


async def request_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
    token = request_id_var.set(request_id)
    request.state.request_id = request_id

    started = time.perf_counter()
    status_code = 500  # if call_next raises, the error handler will answer 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        labels = {"route": _route_template(request), "method": request.method}
        metrics.increment("http_requests_total", {**labels, "status": str(status_code)})
        metrics.observe_ms("http_request_latency", latency_ms, labels)
        request_id_var.reset(token)
