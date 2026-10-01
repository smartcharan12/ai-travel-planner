# 18 — Observability: logs, metrics, traces (Phases 4.12–4.17, 4.31)

Files: [`app/observability/`](../app/observability/) (`logging.py`, `context.py`, `metrics.py`),
[`app/api/middleware.py`](../app/api/middleware.py), instrumented code in `app/llm/client.py`,
`app/graph/research_graph.py`, `app/graph/planning_graph.py`, `app/services/`.

## What is observability?
Being able to answer questions about a running system **from the outside**, without adding code first:
"Why was request 5ece… slow?", "How often does Gemini return an invalid itinerary?", "Did Tavily fail last
night?". It comes from three kinds of data:

| | Logs | Metrics | Traces |
|---|---|---|---|
| Is | one record per event, with details | numbers aggregated over time | the timed path of one request through components |
| Answers | "what happened to *this* request?" | "how much / how often / how fast, *in general*?" | "where did *this* request spend its time?" |
| Here | JSON events: `request_completed`, `llm_call`, `search_call`, … | `/api/v1/metrics` counters + timings | **partial**: events share `request_id` and carry `latency_ms` |

**Honest status of tracing:** there is **no distributed tracing** (no OpenTelemetry spans or trace viewer).
What exists is *log correlation*: every event of a request carries the same `request_id`, in order, with its
own latency, so one request can be reconstructed in Kibana. Real spans (OpenTelemetry → Jaeger or Cloud Trace)
are a future step.

## Where things happen (Phase 4.1 map, verified in the code)

| What | Where |
|---|---|
| LLM calls (3 sites) | `research_graph.extract_entities` → `StructuredLLM.generate(purpose="research_extraction")`; `planning_graph.generate_itinerary` (`"itinerary_planning"`); `planning_graph.repair_itinerary` (`"itinerary_repair"`) |
| Search calls | `research_graph` search nodes → `SearchProvider.search` (5 per request, in parallel) |
| Validation | `planning_graph.validate_itinerary` → `planning/validator.validate_draft` |
| Repair | `planning_graph.repair_itinerary` (bounded by `MAX_REPAIR_ATTEMPTS`) |
| Budget | `planning_graph.budget` → `planning/budget.calculate_budget` |
| Metrics | `observability/metrics.py` registry, written from middleware, LLM client, graphs |
| Logs (before Stage 4) | a few unstructured `logger.warning/error` lines, **no logging configuration**, no per-request line |
| Stage 4 attaches | `configure_logging` in `create_app`; `RequestStats` ContextVar created in middleware; `log_event` calls at each site above |

## Structured JSON logs

One JSON object per line (stdout, plus `LOG_FILE` for Logstash):
```json
{"timestamp": "2026-10-01T15:01:52.565Z", "level": "INFO", "service": "api", "logger": "app.request",
 "event_type": "request_completed", "message": "POST /api/v1/plan -> 200", "request_id": "demo-request-0001",
 "route": "/api/v1/plan", "method": "POST", "status": 200, "latency_ms": 43.5, "destination": "Goa",
 "stage": "itinerary", "demo_mode": true, "model": "demo-model", "search_provider": "demo",
 "error_code": null, "llm_call_count": 3, "search_call_count": 5, "input_tokens": null,
 "output_tokens": null, "repair_attempts": 1}
```
(Real output of a demo request, re-formatted.)

**Why JSON:** Logstash, Elasticsearch and Cloud Logging can filter `status >= 500 and destination: "Goa"`
directly. With sentences you'd need fragile regexes.

### Events

| `event_type` | Written by | Key fields |
|---|---|---|
| `request_completed` | middleware, once per request (not for health/metrics polling) | route, method, status, latency_ms, destination, stage, demo_mode, model, search_provider, error_code, llm_call_count, search_call_count, input/output_tokens, repair_attempts |
| `request_failed` | domain error handler | error_code, status, cause_type, details |
| `unhandled_error` | 500 handler | error_type, stack_trace (server-side only) |
| `search_call` | each search node | provider, category, outcome (ok/empty/error), error_code, latency_ms, result_count, demo_mode |
| `research_grounded` | ground node | hits, extracted, accepted, rejected, rejection_reasons, prices_removed |
| `llm_call` | `StructuredLLM`, once per model call | purpose, model, attempt, outcome, latency_ms, input/output/total_tokens, estimated_cost_usd, demo_mode, error_type |
| `itinerary_validated` | validate node | attempt (0 = first draft), passed, error_codes, warning_codes |
| `itinerary_repair_requested` | repair node | attempt, reasons |
| `itinerary_invalid` | give-up node | repair_attempts, error_codes |
| `plan_completed` | `TravelPlanner` | destination, days, travellers, style, llm_calls, tokens, repair_attempts, final_validation, grounded_activity_ratio, within_budget, budget_complete, search/llm/total latency |

### What is never logged
API keys and headers, prompts and model messages, raw provider responses, `special_requirements` (free text
from the user), budgets are not logged per user. Defence in depth: the formatter drops fields named like
`api_key`, `authorization`, `password`, `secret`, `prompt`, `messages`, `headers`, and Logstash drops them again.

### How the per-request numbers get there
`RequestStats` lives in a `ContextVar` created by the middleware. LangGraph nodes run in asyncio tasks that get
a *copy* of the context pointing to the *same* object, so each `search_call` / `llm_call` increments counters
the middleware later writes into `request_completed`.

## LLM observability
Per call: model, purpose, latency, outcome (`ok`, `invalid_output`, `timeout`, `rate_limited`, `auth_error`,
`error`…), tokens. **Tokens** come from the provider's `usage_metadata`; if absent they are `null`
(unknown), **never 0**. The demo model reports none, so demo logs show `null`. **Cost** is computed only if
`LLM_INPUT_COST_PER_MILLION_USD` and `LLM_OUTPUT_COST_PER_MILLION_USD` are set *and* tokens are known;
otherwise `null`. Prices change and are not hard-coded, because a stale price would give confident wrong costs.

**Application monitoring vs LLM observability:** the first asks "is the service up and fast?" (status codes,
latency). The second asks "is the AI behaving and affordable?" (invalid outputs, repairs, grounding rejections,
tokens, cost). Same logs, different fields.

## Metrics (`GET /api/v1/metrics`)

| Metric | Labels | Meaning |
|---|---|---|
| `http_requests_total` | route, method, status | requests (the spec's `requests_total`; kept under its Stage 1 name) |
| `http_request_latency` | route, method | count / avg / max ms |
| `search_calls_total` | provider, category, outcome | search API calls |
| `search_latency` | provider | per-call ms |
| `llm_calls_total` | model, purpose, outcome | model calls, including invalid-output retries |
| `llm_latency` | model, purpose | per-call ms |
| `llm_tokens_total` | model, purpose, direction | tokens, only when reported |
| `grounding_rejections_total` | — | extracted entities rejected by grounding |
| `itinerary_first_draft_total` | result=valid/invalid | → *how often does the LLM produce an invalid itinerary?* |
| `validation_failures_total` | code | which rules fail |
| `repair_attempts_total` | — | repair rounds started |
| `repair_success_total` | — | validations passed after ≥ 1 repair |
| `itinerary_invalid_total` | — | gave up after max repairs → *repair success rate = success / (success + invalid)* |
| `budget_overflow_total`, `budget_incomplete_total` | — | plans over budget / with unknown costs |
| `research_workflow_latency`, `plan_workflow_latency` | — | end-to-end workflow ms |

Every metric above is emitted by code and covered by `tests/unit/test_observability.py`. Limitation: in-process
memory, per container, reset on restart. Durable, cross-container analysis comes from logs in ELK. A
Prometheus exporter is a possible later step.

## Cost and performance (Phase 4.31)

**Measured (demo mode, this machine, 20 requests, external calls replaced by offline stand-ins):**
workflow total median **32.4 ms** (p95 42.4); demo "LLM" calls ~1.2–1.4 ms; demo searches ~0.03 ms. So **our
own code (graph orchestration, normalisation, grounding, validation, budget, JSON logging) costs about 30 ms
per plan.**

**Not measured (NOT TESTED, no API keys):** real Tavily latency, real Gemini latency, real token counts and
cost. Every live request logs them (`search_call.latency_ms`, `llm_call.latency_ms`, `input_tokens`…), so the
first live run produces the real numbers.

**Where time and money go (by design):**

| Step | Calls per plan | Expected share |
|---|---|---|
| Search | 5 (parallel → wall time ≈ slowest) | moderate; Tavily credits per call |
| Extraction LLM | 1 (+1 if output invalid) | large input (sources) → most input tokens |
| Planning LLM | 1 | large output (JSON itinerary) |
| Repair LLM | 0–2 | each repeats most of the planning cost |
| Everything else | — | ~30 ms (measured) |

**Reducing LLM calls:** fewer repairs through better prompts (watch `itinerary_first_draft_total{result=invalid}`
and `validation_failures_total{code}` to see *which* rules fail); repair only failing days; lower
`MAX_REPAIR_ATTEMPTS`; trim `SEARCH_MAX_CONTENT_CHARS` / `MAX_ENTITIES_PER_CATEGORY` to cut input tokens.
**Reducing search calls:** merge categories into fewer queries; skip transport search when no origin is given.
**Caching later:** cache *research* per destination + query for hours (most cost, and travel facts change
slowly); never cache itineraries across users with different preferences. Not built yet, deliberately: it adds
invalidation complexity, and we need real usage numbers first.

## BEGINNER EXPLANATION
Logs are the diary ("10:03, request 5ece asked for Goa; Gemini took 2.3 s; repaired once"). Metrics are the
dashboard gauges ("today: 120 plans, 18% needed repair"). Traces would be a stopwatch on each leg of one
journey. We have the diary and gauges, and a diary detailed enough to rebuild each journey by request id.
