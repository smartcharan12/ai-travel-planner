"""Turn every failure into the same ``ErrorResponse`` JSON shape.

Three handlers, from most to least specific:

1. ``TravelPlannerError``  our own domain errors -> their code + status
2. ``RequestValidationError``  bad request body -> 422 with field-level details
3. ``Exception``  anything unexpected -> generic 500. The real error is
   kept for server logs, but its text is NOT sent to the client because
   it can leak internals (file paths, SQL, upstream URLs with keys...).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import TravelPlannerError
from app.schemas import ErrorBody, ErrorResponse


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_json(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(error=body).model_dump(mode="json"))


async def handle_domain_error(request: Request, exc: TravelPlannerError) -> JSONResponse:
    return _error_json(
        exc.http_status,
        ErrorBody(
            code=exc.code,
            message=exc.public_message,
            request_id=_request_id(request),
            details=exc.details,
        ),
    )


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Report where and why, but drop Pydantic's "input" echo: no need to
    # reflect user-supplied text back, and it keeps error payloads small.
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
    # Stage 4 adds structured logging of `exc` with its traceback here.
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
