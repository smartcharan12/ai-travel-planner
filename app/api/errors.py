"""Turn every failure into the same ``ErrorResponse`` JSON shape.

Three handlers, from most to least specific:

1. ``TravelPlannerError``  our own domain errors -> their code + status
2. ``RequestValidationError``  bad request body -> 422 with field-level details
3. ``Exception``  anything unexpected -> generic 500. The real error is
   kept for server logs, but its text is NOT sent to the client because
   it can leak internals (file paths, SQL, upstream URLs with keys...).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import TravelPlannerError
from app.observability.context import current_stats
from app.observability.logging import log_event
from app.schemas import ErrorBody, ErrorResponse

logger = logging.getLogger(__name__)


def _note_error(code: str) -> None:
    stats = current_stats()
    if stats is not None:
        stats.error_code = code


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_json(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(error=body).model_dump(mode="json"))


async def handle_domain_error(request: Request, exc: TravelPlannerError) -> JSONResponse:
    # Log the code and the type of the underlying cause (e.g. ReadTimeout), not its message,
    # which for provider errors may echo request details.
    cause = type(exc.__cause__).__name__ if exc.__cause__ else None
    _note_error(exc.code)
    log_event(
        logger,
        "request_failed",
        exc.public_message,
        level=logging.WARNING,
        error_code=exc.code,
        status=exc.http_status,
        cause_type=cause,
        details=exc.details,
    )
    response = _error_json(
        exc.http_status,
        ErrorBody(
            code=exc.code,
            message=exc.public_message,
            request_id=_request_id(request),
            details=exc.details,
        ),
    )
    if "retry_after_seconds" in exc.details:  # standard hint for well-behaved clients
        response.headers["Retry-After"] = str(exc.details["retry_after_seconds"])
    return response


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Report where and why, but drop Pydantic's "input" echo: no need to
    # reflect user-supplied text back, and it keeps error payloads small.
    _note_error("INVALID_REQUEST")
    fields = [
        {"field": ".".join(str(part) for part in err["loc"] if part != "body"), "message": err["msg"]}
        for err in exc.errors()
    ]
    return _error_json(
        422,
        ErrorBody(
            code="INVALID_REQUEST",
            message="The request body failed validation.",
            request_id=_request_id(request),
            details={"fields": jsonable_encoder(fields)},
        ),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Full traceback goes to the server log only (structured JSON logging arrives in Stage 4).
    _note_error("INTERNAL_ERROR")
    logger.error(
        "unhandled error",
        exc_info=exc,
        extra={"event_type": "unhandled_error", "fields": {"request_id": _request_id(request)}},
    )
    return _error_json(
        500,
        ErrorBody(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            request_id=_request_id(request),
        ),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TravelPlannerError, handle_domain_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unexpected_error)
