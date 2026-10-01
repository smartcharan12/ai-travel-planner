"""Structured LLM calls: messages in, validated Pydantic object out.

``StructuredLLM`` wraps any LangChain chat model (Gemini in production, a demo
or fake model offline) and adds everything an application needs around a raw
model call:

1. **Schema constraint**: for Gemini, the Pydantic JSON Schema is sent as
   ``response_json_schema`` with ``response_mime_type=application/json``, so
   the model is steered to valid JSON while generating.
2. **Verification**: the reply is parsed and validated with Pydantic anyway;
   constraints reduce bad output, they don't guarantee its absence.
3. **Bounded output retry**: if the JSON is malformed or fails validation,
   the model is shown the errors once (``LLM_OUTPUT_RETRIES``) and asked
   again. After that, ``LLMOutputError``, never an infinite loop.
4. **Hard timeout**: ``asyncio.wait_for`` caps the total wait even if the SDK's
   own timeout/retry logic misbehaves.
5. **Error translation**: provider/LangChain exceptions become our domain
   errors. Provider messages are logged server-side, never returned to users.
6. **Observability**: per call, one ``llm_call`` JSON log line (purpose, model,
   latency, outcome, tokens if the provider reports them, cost if rates are
   configured) plus metrics and per-request counters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Generic, TypeVar

import httpx
from langchain_core.exceptions import (
    ContextOverflowError,
    ModelAuthenticationError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from app.core.exceptions import (
    ConfigurationError,
    LLMAuthError,
    LLMError,
    LLMOutputError,
    LLMTimeoutError,
    RateLimitError,
)
from app.observability.context import current_stats
from app.observability.logging import log_event
from app.observability.metrics import metrics

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass
class LLMUsage:
    """Accumulated cost/latency facts for one or more model calls."""

    calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float = 0.0

    def add_call(self, message: AIMessage | None, latency_ms: float) -> None:
        self.calls += 1
        self.latency_ms += latency_ms
        usage = getattr(message, "usage_metadata", None) if message is not None else None
        if usage:  # providers that don't report tokens leave these as None (unknown, not 0)
            self.input_tokens = (self.input_tokens or 0) + int(usage.get("input_tokens", 0))
            self.output_tokens = (self.output_tokens or 0) + int(usage.get("output_tokens", 0))


def merge_usage(usages: list[LLMUsage]) -> LLMUsage:
    """Sum several calls' usage (tokens stay None if no call reported them)."""
    total = LLMUsage()
    for u in usages:
        total.calls += u.calls
        total.latency_ms += u.latency_ms
        for attr in ("input_tokens", "output_tokens"):
            value = getattr(u, attr)
            if value is not None:
                setattr(total, attr, (getattr(total, attr) or 0) + value)
    return total


@dataclass
class StructuredResult(Generic[T]):
    value: T
    usage: LLMUsage = field(default_factory=LLMUsage)


def parse_json_reply(text: str, schema: type[T]) -> T:
    """Parse model text into ``schema``. Raises JSONDecodeError or ValidationError."""
    cleaned = _CODE_FENCE.sub("", text.strip())  # models sometimes wrap JSON in ```json fences
    return schema.model_validate(json.loads(cleaned))


def _describe_invalid_output(exc: Exception) -> str:
    """Short, model-readable explanation of what was wrong with its last reply."""
    if isinstance(exc, ValidationError):
        problems = [
            f"- {'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}" for err in exc.errors()[:8]
        ]
        return "The JSON did not match the schema:\n" + "\n".join(problems)
    return f"The reply was not valid JSON ({type(exc).__name__})."


class StructuredLLM:
    def __init__(
        self,
        chat_model: BaseChatModel,
        *,
        model_name: str,
        timeout_seconds: float,
        output_retries: int = 1,
        native_json_schema: bool = True,
        is_demo: bool = False,
        input_cost_per_million_usd: float | None = None,
        output_cost_per_million_usd: float | None = None,
    ):
        self._model = chat_model
        self.model_name = model_name
        self._timeout = timeout_seconds
        self._output_retries = output_retries
        self._native_json_schema = native_json_schema
        self.is_demo = is_demo
        self._input_rate = input_cost_per_million_usd
        self._output_rate = output_cost_per_million_usd

    async def generate(
        self, messages: list[BaseMessage], schema: type[T], *, purpose: str = "llm"
    ) -> StructuredResult[T]:
        """Call the model until it returns valid ``schema`` JSON, or raise a domain error.

        ``purpose`` ("research_extraction", "itinerary_planning", "itinerary_repair")
        labels logs and metrics so each kind of call can be analysed separately.
        """
        runnable = self._model
        if self._native_json_schema:
            runnable = self._model.bind(
                response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(),
            )

        usage = LLMUsage()
        conversation = list(messages)
        last_error: Exception | None = None
        for attempt in range(1, self._output_retries + 2):
            reply, latency_ms = await self._invoke(runnable, conversation, usage, purpose, attempt)
            text = reply.text  # concatenated text parts (ignores e.g. 'thinking' blocks)
            try:
                value = parse_json_reply(text, schema)
                self._observe_call(purpose, attempt, "ok", latency_ms, reply)
                return StructuredResult(value=value, usage=usage)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                self._observe_call(
                    purpose, attempt, "invalid_output", latency_ms, reply, error_type=type(exc).__name__
                )
                # Show the model its own answer and what was wrong, then ask again.
                conversation += [
                    AIMessage(content=text[:4000]),
                    HumanMessage(
                        content=_describe_invalid_output(exc)
                        + "\nReply again with ONLY one JSON object that matches the schema."
                    ),
                ]

        reason = "schema_validation" if isinstance(last_error, ValidationError) else "invalid_json"
        raise LLMOutputError(details={"reason": reason, "attempts": self._output_retries + 1})

    async def _invoke(
        self, runnable, conversation: list[BaseMessage], usage: LLMUsage, purpose: str, attempt: int
    ) -> tuple[AIMessage, float]:
        started = time.perf_counter()

        def fail(outcome: str, exc: Exception) -> None:
            latency_ms = (time.perf_counter() - started) * 1000
            usage.add_call(None, latency_ms)
            self._observe_call(purpose, attempt, outcome, latency_ms, None, error_type=type(exc).__name__)

        try:
            reply = await asyncio.wait_for(runnable.ainvoke(conversation), timeout=self._timeout)
        except (TimeoutError, ModelTimeoutError, httpx.TimeoutException) as exc:
            fail("timeout", exc)
            raise LLMTimeoutError(details={"model": self.model_name}) from exc
        except ModelRateLimitError as exc:
            fail("rate_limited", exc)
            raise RateLimitError(
                "The AI model is rate-limiting us. Please try again shortly.",
                details={"provider": "llm", "upstream": True},
            ) from exc
        except (ModelAuthenticationError, ModelPermissionDeniedError) as exc:
            fail("auth_error", exc)
            raise LLMAuthError(details={"model": self.model_name}) from exc
        except ModelNotFoundError as exc:
            fail("model_not_found", exc)
            raise ConfigurationError(details={"reason": "llm_model_not_found"}) from exc
        except ContextOverflowError as exc:
            fail("context_overflow", exc)
            raise LLMError("The research data was too large for the AI model.") from exc
        except Exception as exc:  # any other SDK/network failure: report generically, log the type
            fail("error", exc)
            raise LLMError(details={"model": self.model_name}) from exc

        latency_ms = (time.perf_counter() - started) * 1000
        usage.add_call(reply, latency_ms)
        return reply, latency_ms

    def _estimate_cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        """Only when rates are configured AND the provider reported tokens; otherwise unknown."""
        if None in (self._input_rate, self._output_rate, input_tokens, output_tokens):
            return None
        return round((input_tokens * self._input_rate + output_tokens * self._output_rate) / 1_000_000, 6)

    def _observe_call(
        self,
        purpose: str,
        attempt: int,
        outcome: str,
        latency_ms: float,
        reply: AIMessage | None,
        *,
        error_type: str | None = None,
    ) -> None:
        """Metrics + one structured log line + per-request counters for a single model call."""
        tokens = (getattr(reply, "usage_metadata", None) or {}) if reply is not None else {}
        input_tokens = tokens.get("input_tokens")
        output_tokens = tokens.get("output_tokens")
        total_tokens = tokens.get("total_tokens")
        labels = {"model": self.model_name, "purpose": purpose}

        metrics.increment("llm_calls_total", {**labels, "outcome": outcome})
        metrics.observe_ms("llm_latency", latency_ms, labels)
        if input_tokens is not None:
            metrics.increment("llm_tokens_total", {**labels, "direction": "input"}, int(input_tokens))
        if output_tokens is not None:
            metrics.increment("llm_tokens_total", {**labels, "direction": "output"}, int(output_tokens))

        stats = current_stats()
        if stats is not None:
            stats.llm_call_count += 1
            stats.add_tokens(input_tokens, output_tokens)

        log_event(
            logger,
            "llm_call",
            f"{purpose} -> {outcome}",
            level=logging.INFO if outcome == "ok" else logging.WARNING,
            purpose=purpose,
            model=self.model_name,
            attempt=attempt,
            outcome=outcome,
            latency_ms=round(latency_ms, 1),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=self._estimate_cost(input_tokens, output_tokens),
            demo_mode=self.is_demo,
            error_type=error_type,
        )
