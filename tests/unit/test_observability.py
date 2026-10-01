"""Structured logging, request context, LLM/search/repair observability and metrics."""

from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.llm.client import StructuredLLM
from app.observability.context import RequestStats, request_id_var, request_stats_var
from app.observability.logging import JsonFormatter, configure_logging, log_event
from app.observability.metrics import metrics
from app.schemas import ResearchExtraction
from tests.fakes import ScriptedChatModel, goa_extraction_json


def _record(event_type="x", **fields) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "hello", None, None)
    record.event_type = event_type
    record.fields = fields
    return record


def _events(caplog, event_type):
    return [r for r in caplog.records if getattr(r, "event_type", None) == event_type]


def _counter_delta(before: dict, after: dict, key: str) -> int:
    return after["counters"].get(key, 0) - before["counters"].get(key, 0)


# ---------- formatter ----------
def test_json_formatter_emits_one_object_with_fields_and_request_id():
    token = request_id_var.set("req-123")
    try:
        line = JsonFormatter("api").format(_record("llm_call", model="m", latency_ms=12.5, input_tokens=10))
    finally:
        request_id_var.reset(token)
    data = json.loads(line)
    assert data["event_type"] == "llm_call" and data["request_id"] == "req-123"
    assert data["model"] == "m" and data["latency_ms"] == 12.5 and data["input_tokens"] == 10
    assert data["level"] == "INFO" and data["timestamp"].endswith("Z")
    assert data["severity"] == "INFO"  # Cloud Logging's level field


def test_secret_looking_fields_are_dropped():
    line = JsonFormatter("api").format(
        _record(
            api_key="AIzaSECRET",
            tavily_api_key="tvly-x",
            authorization="Bearer y",
            prompt="full prompt",
            output_tokens=5,
        )
    )
    data = json.loads(line)
    assert (
        "AIzaSECRET" not in line
        and "tvly-x" not in line
        and "Bearer" not in line
        and "full prompt" not in line
    )
    assert data["output_tokens"] == 5  # token COUNTS are not secrets


def test_exception_is_serialised_with_type_and_stack():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record()
        record.exc_info = sys.exc_info()
    data = json.loads(JsonFormatter("api").format(record))
    assert data["error_type"] == "ValueError" and "boom" in data["stack_trace"]


def test_configure_logging_is_idempotent_and_writes_json_file(tmp_path):
    log_file = tmp_path / "app.jsonl"
    configure_logging(level="INFO", fmt="text", log_file=str(log_file))
    configure_logging(level="INFO", fmt="text", log_file=str(log_file))
    ours = [h for h in logging.getLogger().handlers if getattr(h, "_travel_planner_handler", False)]
    assert len(ours) == 2  # stdout + file, not duplicated
    log_event(logging.getLogger("app.test"), "unit_test_event", value=1)
    lines = log_file.read_text().strip().splitlines()
    assert json.loads(lines[-1])["event_type"] == "unit_test_event"  # file is JSON even in text mode
    s = get_settings()
    configure_logging(level=s.log_level, fmt=s.log_format)


# ---------- request lifecycle through the API ----------
def test_request_completed_event_carries_request_stats(client, goa_payload, caplog):
    caplog.set_level(logging.INFO)
    resp = client.post("/api/v1/plan", json=goa_payload, headers={"X-Request-ID": "trace-plan-0001"})
    assert resp.status_code == 200
    (event,) = [r for r in _events(caplog, "request_completed") if r.fields["route"] == "/api/v1/plan"]
    f = event.fields
    assert f["status"] == 200 and f["destination"] == "Goa" and f["stage"] == "itinerary"
    assert f["demo_mode"] is True and f["search_call_count"] == 5 and f["llm_call_count"] == 3
    assert f["repair_attempts"] == 1 and f["error_code"] is None and f["latency_ms"] > 0


def test_every_workflow_event_shares_the_request_id(client, goa_payload, caplog):
    caplog.set_level(logging.INFO)
    client.post("/api/v1/plan", json=goa_payload, headers={"X-Request-ID": "trace-plan-0002"})
    types = {r.event_type for r in caplog.records if getattr(r, "event_type", None)}
    assert {
        "search_call",
        "llm_call",
        "research_grounded",
        "itinerary_validated",
        "itinerary_repair_requested",
        "plan_completed",
        "request_completed",
    } <= types
    formatter = JsonFormatter("api")
    for r in caplog.records:
        if getattr(r, "event_type", None) in {"search_call", "llm_call", "plan_completed"}:
            # the context var is live while the record is created; formatting later uses fields/record
            assert json.loads(formatter.format(r))["event_type"] == r.event_type


def test_error_code_is_recorded_on_failed_requests(client, make_settings, goa_payload, caplog):
    caplog.set_level(logging.INFO)
    client.app.dependency_overrides[get_settings] = lambda: make_settings(tavily_api_key="tvly-SECRET-xyz")
    assert client.post("/api/v1/plan", json=goa_payload).status_code == 503
    (event,) = [r for r in _events(caplog, "request_completed") if r.fields["route"] == "/api/v1/plan"]
    assert event.fields["error_code"] == "CONFIGURATION_ERROR" and event.levelno == logging.ERROR  # 5xx
    assert "tvly-SECRET-xyz" not in caplog.text


def test_health_polling_is_not_logged_but_is_counted(client, caplog):
    caplog.set_level(logging.INFO)
    client.get("/api/v1/health")
    assert not [r for r in _events(caplog, "request_completed") if r.fields["route"] == "/api/v1/health"]


# ---------- metrics ----------
def test_plan_metrics_answer_the_repair_questions(client, goa_payload):
    before = metrics.snapshot()
    client.post("/api/v1/plan", json=goa_payload)
    after = metrics.snapshot()
    delta = lambda k: _counter_delta(before, after, k)  # noqa: E731
    assert delta("itinerary_first_draft_total{result=invalid}") == 1  # demo plants A99
    assert delta("repair_attempts_total") == 1
    assert delta("repair_success_total") == 1
    assert delta("validation_failures_total{code=UNKNOWN_PLACE_ID}") == 1
    assert delta("search_calls_total{category=hotels,outcome=ok,provider=demo}") == 1
    assert delta("llm_calls_total{model=demo-model,outcome=ok,purpose=itinerary_repair}") == 1
    assert delta("grounding_rejections_total") == 1
    assert delta("budget_overflow_total") == 1  # demo totals exceed ₹25,000
    assert "llm_latency{model=demo-model,purpose=itinerary_planning}" in after["timings_ms"]


# ---------- LLM call observability ----------
def _llm(script, usage=None, **rates):
    return StructuredLLM(
        ScriptedChatModel(script=script, usage=usage),
        model_name="gemini-test",
        timeout_seconds=5,
        native_json_schema=False,
        **rates,
    )


def test_llm_call_event_has_tokens_and_cost_when_known(caplog):
    caplog.set_level(logging.INFO)
    llm = _llm(
        [json.dumps(goa_extraction_json())],
        usage={"input_tokens": 2000, "output_tokens": 500, "total_tokens": 2500},
        input_cost_per_million_usd=0.30,
        output_cost_per_million_usd=2.50,
    )
    asyncio.run(llm.generate([HumanMessage("x")], ResearchExtraction, purpose="research_extraction"))
    (event,) = _events(caplog, "llm_call")
    f = event.fields
    assert (f["input_tokens"], f["output_tokens"], f["total_tokens"]) == (2000, 500, 2500)
    assert f["estimated_cost_usd"] == round((2000 * 0.30 + 500 * 2.50) / 1e6, 6)
    assert f["purpose"] == "research_extraction" and f["outcome"] == "ok"


def test_unknown_tokens_and_rates_stay_null_not_zero(caplog):
    caplog.set_level(logging.INFO)
    asyncio.run(_llm([json.dumps(goa_extraction_json())]).generate([HumanMessage("x")], ResearchExtraction))
    f = _events(caplog, "llm_call")[0].fields
    assert f["input_tokens"] is None and f["estimated_cost_usd"] is None


def test_invalid_output_attempts_are_logged_and_counted_per_request(caplog):
    caplog.set_level(logging.INFO)
    stats = RequestStats(request_id="r")
    token = request_stats_var.set(stats)
    try:
        llm = _llm(
            ["{bad", json.dumps(goa_extraction_json())],
            usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        asyncio.run(llm.generate([HumanMessage("x")], ResearchExtraction))
    finally:
        request_stats_var.reset(token)
    outcomes = [e.fields["outcome"] for e in _events(caplog, "llm_call")]
    assert outcomes == ["invalid_output", "ok"]
    assert stats.llm_call_count == 2 and stats.input_tokens == 20
