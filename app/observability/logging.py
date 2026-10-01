"""Structured JSON logging.

Every log line is one JSON object, so machines (Logstash, Elasticsearch,
Cloud Logging) can filter on fields instead of parsing sentences:

    {"timestamp": "2026-10-01T10:12:03.512Z", "level": "INFO", "service": "api",
     "event_type": "llm_call", "request_id": "5ece24f3…", "purpose": "itinerary_planning",
     "model": "gemini-2.5-flash", "latency_ms": 2380.1, "outcome": "ok",
     "input_tokens": 1500, "output_tokens": 800, ...}

Use ``log_event(logger, "event_type", **fields)`` for anything worth querying.
Plain ``logger.warning("...")`` calls still work and come out as JSON too.

Safety: field names that look like secrets (api_key, authorization, password,
secret, prompt, messages) are dropped before writing, a second line of
defence after "never pass them in the first place".

Destinations: stdout always (what Docker/Kubernetes collect), plus an
optional rotating file (``LOG_FILE``) that Logstash tails in docker-compose.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from typing import Any

from app.observability.context import current_request_id

_REDACTED_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "prompt", "messages", "headers"}
_HANDLER_MARK = "_travel_planner_handler"


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return k in _REDACTED_KEYS or k.endswith(("_api_key", "_secret", "_password"))


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            # Cloud Logging reads the log level from a field named `severity`.
            "severity": record.levelname,
            "service": self.service,
            "logger": record.name,
            "event_type": getattr(record, "event_type", "log"),
            "message": record.getMessage(),
            # The context var is unset for logs written after the middleware finished
            # (e.g. the unhandled-error handler), so an explicit field is accepted too.
            "request_id": current_request_id() or (getattr(record, "fields", None) or {}).get("request_id"),
        }
        for key, value in (getattr(record, "fields", None) or {}).items():
            if not _is_sensitive(key) and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-friendly alternative for local debugging (LOG_FORMAT=text)."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {k: v for k, v in (getattr(record, "fields", None) or {}).items() if not _is_sensitive(k)}
        extra = " ".join(f"{k}={v}" for k, v in fields.items())
        rid = current_request_id()
        base = f"{record.levelname:<7} {getattr(record, 'event_type', 'log'):<22} {record.getMessage()}"
        text = f"{base} {extra}{f' request_id={rid}' if rid else ''}".rstrip()
        if record.exc_info:
            text += "\n" + self.formatException(record.exc_info)
        return text


def log_event(
    logger: logging.Logger,
    event_type: str,
    message: str | None = None,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Write one structured event. ``fields`` become top-level JSON keys."""
    logger.log(level, message or event_type, extra={"event_type": event_type, "fields": fields})


def configure_logging(
    *, level: str = "INFO", fmt: str = "json", log_file: str | None = None, service: str = "api"
) -> None:
    """Install our handlers on the root logger (idempotent: safe to call twice).

    Uvicorn's own loggers are routed through the same handlers; its access log
    is silenced because the middleware writes a richer ``request_completed`` event.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)

    formatter: logging.Formatter = JsonFormatter(service) if fmt == "json" else TextFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        # Rotation keeps local disk use bounded: 3 × 10 MB.
        handlers.append(logging.handlers.RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=3))
    for handler in handlers:
        handler.setFormatter(
            JsonFormatter(service) if isinstance(handler, logging.FileHandler) else formatter
        )
        setattr(handler, _HANDLER_MARK, True)
        root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # Third-party HTTP clients log every request at INFO, which is noise for us.
    for noisy in ("httpx", "httpx2", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
