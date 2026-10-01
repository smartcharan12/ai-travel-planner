"""Per-request context shared by the middleware, the workflow and the logger.

A ``ContextVar`` is a variable whose value is private to the current request,
even though many requests run concurrently. LangGraph runs nodes in asyncio
tasks; each task gets a *copy* of the context, but the copy points at the same
``RequestStats`` object, so a search node incrementing ``search_calls`` is
visible to the middleware when it writes the final ``request_completed`` log.

Outside an HTTP request (CLI, evaluation runner, unit tests) there is no
context: ``current_stats()`` returns None and callers simply skip it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import asdict, dataclass


@dataclass
class RequestStats:
    request_id: str
    destination: str | None = None
    stage: str | None = None  # "research" | "itinerary"
    demo_mode: bool | None = None
    model: str | None = None
    search_provider: str | None = None
    error_code: str | None = None
    llm_call_count: int = 0
    search_call_count: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    repair_attempts: int | None = None

    def add_tokens(self, input_tokens: int | None, output_tokens: int | None) -> None:
        if input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + input_tokens
        if output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + output_tokens

    def as_log_fields(self) -> dict:
        fields = asdict(self)
        fields.pop("request_id")
        return fields


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
request_stats_var: ContextVar[RequestStats | None] = ContextVar("request_stats", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()


def current_stats() -> RequestStats | None:
    return request_stats_var.get()
