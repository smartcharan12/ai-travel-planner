# File guide

Every major directory, then every major file, in the order a request meets them. Status: final (Stage 5).

## Directories

| Directory | Purpose | Important files | Depends on | Data flow | Example |
|---|---|---|---|---|---|
| `app/api/` | HTTP layer | `routes.py`, `middleware.py`, `errors.py`, `limits.py` | schemas, services, observability | HTTP JSON → `TravelRequest` → service → response JSON | `POST /api/v1/plan` |
| `app/schemas/` | data contracts | `request.py`, `research.py`, `planning.py`, `itinerary.py`, `response.py` | pydantic | shared by every layer | `TravelRequest`, `ItineraryDraft` |
| `app/services/` | run a workflow for a request | `travel_planner.py`, `research_planner.py` | graph, llm, tools | request → graph → response + `plan_completed` log | `TravelPlanner(settings).run(req, id)` |
| `app/graph/` | LangGraph orchestration | `research_graph.py`, `planning_graph.py`, `state.py` | research, planning, llm, tools | state flows node → node | 5 parallel searches; repair loop |
| `app/research/` | queries, normalisation, grounding | `queries.py`, `normalizer.py`, `grounding.py` | schemas | hits → verified entities | rejects unverified names |
| `app/tools/search/` | search providers | `tavily.py`, `serper.py`, `demo.py`, `factory.py` | httpx | query → `SearchResultItem`s | Tavily POST |
| `app/llm/`, `app/prompts/` | model calls and prompts | `client.py`, `factory.py`, `demo_model.py`, prompt files | langchain, google-genai | messages → validated JSON | extraction, planning, repair |
| `app/planning/` | deterministic plan logic | optimizer, validator, named_places, titles, assembler, budget, quality | schemas | draft → itinerary + budget | `OVER_BUDGET` warning |
| `app/observability/` | logs, context, metrics | `logging.py`, `context.py`, `metrics.py` | stdlib | events → stdout/file; counters → `/metrics` | `llm_call` event |
| `frontend/` | Streamlit UI | `app.py`, `api_client.py`, `presenters.py`, `Dockerfile` | streamlit, httpx | form → API → rendered plan | DEMO banner |
| `evaluation/` | offline LLM evaluation | `runner.py`, `metrics/`, `datasets/` | deepeval, app | dataset → planner → metrics → JSON report | 8/10 demo cases pass |
| `tests/` | offline test suite | `unit/`, `api/`, `integration/`, `frontend/`, `live/`, `fakes.py` | pytest | fakes → real code → asserts | 300 passed |
| `monitoring/elk/` | local log stack | Logstash pipeline, ES template, Kibana setup | docker-compose | log file → ES → Kibana | saved search "LLM call failures" |
| `infrastructure/kubernetes/` | cluster manifests | `base/`, `overlays/local`, `overlays/gke` | kustomize | YAML → cluster | `kubectl apply -k …/overlays/local` |
| `.github/workflows/` | CI/CD | `ci.yml`, `deploy.yml`, `eval-live.yml` | GitHub Actions | push → checks → images → GKE | PR runs 300 tests |
| `docs/` | learning material | numbered chapters, guides | — | — | start at README |

---

## Entry points

### `app/main.py`
- **Purpose:** build the FastAPI app (`create_app`), configure logging, install middleware, error handlers, routes.
- **Why separate:** all wiring in one readable place; tests build fresh apps.
- **In → Out:** settings → `FastAPI` instance.
- **Depends on:** `api/*`, `config.py`, `observability/logging.py`.
- **Runs when:** process start (`uvicorn app.main:app`).
- **Example:** `TestClient(create_app())` in tests.

### `app/config.py`
- **Purpose:** typed settings from env vars / `.env` (`Settings`, `get_settings`).
- **Why separate:** one source of configuration; secrets as `SecretStr`; blank values = not set.
- **In → Out:** environment → validated `Settings` (`missing_secrets()`, `is_demo`).
- **Runs when:** first `get_settings()` (cached).
- **Example:** `Settings(demo_mode=True)` → providers fake + mock.

## HTTP layer: `app/api/`

### `middleware.py`
- **Purpose:** request id, `RequestStats` context, latency metrics, one `request_completed` JSON log per request.
- **In → Out:** HTTP request → response with `X-Request-ID`; metrics + log line.
- **Depends on:** `observability/context.py`, `logging.py`, `metrics.py`.
- **Example:** `X-Request-ID: trace-plan-0001` is reused and appears in every log event.

### `routes.py`
- **Purpose:** endpoints `/plan`, `/research`, `/health`, `/health/ready`, `/version`, `/metrics`.
- **Why separate:** thin HTTP layer; logic lives in services.
- **In → Out:** validated `TravelRequest` → `TravelResponse` / `ResearchResponse`.
- **Depends on:** `dependencies.py`, `schemas`, `services`.

### `dependencies.py`
- **Purpose:** `get_planner`, `get_research_planner` (overridable in tests).

### `limits.py`
- **Purpose:** per-client requests-per-minute and per-replica concurrency limits on `/plan` and `/research`.
- **Why separate:** protection policy, independent of business logic; uses `app.state` so each app instance has its own.
- **Example:** 21st request in a minute → 429 `RATE_LIMITED` with `Retry-After`.

### `errors.py`
- **Purpose:** map exceptions to the standard `ErrorResponse`; log `request_failed` / `unhandled_error`; record `error_code` in request stats.
- **Example:** `SearchTimeoutError` → 504 `{"error": {"code": "SEARCH_TIMEOUT", ...}}`.

## Contracts: `app/schemas/`
| File | Holds | Produced by → consumed by |
|---|---|---|
| `request.py` | `TravelRequest`, `TravelPreferences`, enums | user → whole workflow |
| `research.py` | `SearchHit`, `ResearchQuery`, entities, `ResearchResult`, `GroundingReport` | research nodes → planner |
| `extraction.py` | `ResearchExtraction` (LLM output #1) | Gemini → grounding |
| `planning.py` | `ItineraryDraft`, `DraftActivity` (LLM output #2; **no titles/prices**; `place_id` XOR `generic_kind`) | Gemini → optimizer/validator/assembler |
| `itinerary.py` | `Itinerary`, `Activity`, `GenericActivity`, `BudgetBreakdown` | assembler/budget → response |
| `response.py` | `TravelResponse`, `ResearchResponse`, `QualityReport`, errors, ops responses | services → API |
| `common.py` | `Source`, `PriceInfo`, `CostBasis` | shared |

## Orchestration
### `app/services/travel_planner.py` / `research_planner.py`
- **Purpose:** check configuration, build providers, run the graph, assemble the response, log `plan_completed`.
- **Why separate:** keeps HTTP out of the graph and graph details out of routes; reused by CLI and evaluation.
- **In → Out:** `TravelRequest` → `TravelResponse` (or `ResearchResponse`).
- **Example:** `await TravelPlanner(Settings(demo_mode=True)).run(request, "r1")`.

### `app/services/common.py`
- **Purpose:** configuration check (no silent demo fallback), provider resolution, data notice, request annotation.

### `app/graph/research_graph.py`
- **Purpose:** LangGraph nodes: prepare_queries → 5 parallel searches → aggregate → extract (Gemini) → ground.
  `add_research_nodes()` lets the planning graph reuse them.
- **Out:** state with `hits`, `research`, `grounding`; `search_call`/`research_grounded` logs.

### `app/graph/planning_graph.py`
- **Purpose:** research nodes + check → generate → optimize → validate ⇄ repair (bounded) → assemble → budget → quality.
- **Out:** state with `itinerary`, `budget`, `quality`; validation/repair logs and metrics.

### `app/graph/state.py`
- **Purpose:** `ResearchState` / `PlannerState` TypedDicts with reducers for parallel writes.

## Research: `app/research/` and `app/tools/search/`
| File | Purpose | Example |
|---|---|---|
| `research/queries.py` | 5 deterministic queries from a request | "best mid-range hotels in Goa price per night" |
| `tools/search/base.py` | `SearchProvider` interface + HTTP error mapping | 401 → `SearchAuthError` |
| `tools/search/tavily.py`, `serper.py` | real providers | Bearer key header |
| `tools/search/demo.py` + `app/demo/data.py` | invented, labelled offline data | `https://demo.invalid/...` |
| `tools/search/factory.py` | pick provider from settings; missing key → error | |
| `research/normalizer.py` | clean, filter, dedupe, number S1..Sn | drops "goal" as a match for "Goa" |
| `research/grounding.py` | verify extracted names and prices against sources | rejects "Dudhsagar Falls" not in S2 |
| `research/text.py` | folding and whole-word matching helpers | "Café" ≈ "cafe" |

## LLM: `app/llm/` and `app/prompts/`
| File | Purpose |
|---|---|
| `llm/client.py` | `StructuredLLM`: JSON-schema binding, Pydantic validation, bounded output retry, timeout, error mapping, `llm_call` logs, tokens, optional cost |
| `llm/factory.py` | build Gemini (`ChatGoogleGenerativeAI`) or the demo model |
| `llm/demo_model.py` | offline deterministic stand-in; plants one fake place (rejected) and one bad id (repaired) |
| `prompts/research_prompt.py` | extraction prompt (v1) |
| `prompts/planner_prompt.py` | planner + repair prompts (v2: place_id XOR generic_kind, sentence case) |

## Planning rules: `app/planning/` (no LLM)
| File | Purpose | Example |
|---|---|---|
| `rules.py` | pace caps, slot cap, rooms, nights | moderate = 4/day |
| `optimizer.py` | order slots, drop repeat attractions, enforce caps, flag backtracking | "removed repeat visit to Baga Beach (A1)" |
| `validator.py` | hard errors + warnings, incl. `UNSUPPORTED_NAMED_PLACE`, `MISSING/CONFLICTING_ACTIVITY_TARGET` | |
| `named_places.py` | detect capitalised place names not in verified research | flags "Imaginary Palace" |
| `titles.py` | titles generated by code | "Dinner at Fisherman's Wharf", "Arrive in Goa" |
| `assembler.py` | draft → `Itinerary` with dates, areas, verified costs | |
| `pricing.py` | source price → group cost (per person / for two / per night) | ₹50 per person × 2 = ₹100 |
| `budget.py`, `budget_rates.py` | deterministic budget with labelled defaults | |
| `quality.py` | grounding ratio, sourced-cost ratio, issues | |

## Observability: `app/observability/`
| File | Purpose |
|---|---|
| `logging.py` | `JsonFormatter`, `log_event`, `configure_logging` (stdout + optional rotating file; secret-looking fields dropped) |
| `context.py` | `request_id_var`, `RequestStats` ContextVar shared by middleware and workflow |
| `metrics.py` | in-process counters and timings behind `/api/v1/metrics` |

## Frontend: `frontend/`
| File | Purpose |
|---|---|
| `app.py` | Streamlit layout: form, spinner, tabs, errors |
| `api_client.py` | HTTP client for `/plan` with error mapping |
| `presenters.py` | pure formatting helpers; `md_escape` against Markdown injection |
| `Dockerfile`, `requirements.txt` | UI image (Streamlit + httpx only) |

## Evaluation: `evaluation/` (offline tooling, not in images)
| File | Purpose |
|---|---|
| `datasets/travel_cases.json` | 10 fixed inputs |
| `dataset.py` | load/validate cases |
| `testcase_builder.py` | response → DeepEval `LLMTestCase` |
| `metrics/deterministic.py` | 7 code metrics (DeepEval `BaseMetric`) |
| `metrics/judge.py` | Faithfulness + 3 G-Eval rubrics with a Gemini judge |
| `runner.py` | `python -m evaluation.runner` → JSON report |
| `test_itinerary.py`, `test_research.py` | `deepeval test run` suites |
| `config.py` | INITIAL ENGINEERING THRESHOLDS |

## Containers and monitoring
| File | Purpose |
|---|---|
| `Dockerfile` | API image: multi-stage, non-root, healthcheck |
| `.dockerignore` | keeps secrets and bulk out of the build context |
| `docker-compose.yml` | api + frontend; `--profile elk` adds ES, Logstash, Kibana, setup |
| `monitoring/elk/logstash/pipeline/travel-planner.conf` | file → JSON → clean → Elasticsearch |
| `monitoring/elk/logstash/config/logstash.yml` | minimal Logstash settings |
| `monitoring/elk/elasticsearch/travel-planner-logs.template.json` | index template / field mappings |
| `monitoring/elk/kibana/setup.sh` | data view + saved searches |

## Kubernetes: `infrastructure/kubernetes/`
| File | Purpose |
|---|---|
| `base/namespace.yaml`, `service-account.yaml` | namespace; one identity per workload, no API token |
| `base/configmap.yaml` | non-secret settings (keys tested against `Settings`) and the API URL for the UI |
| `base/secret.example.yaml` | placeholders only; not deployed |
| `base/api-deployment.yaml`, `frontend-deployment.yaml` | pods with probes, resources, security contexts, graceful shutdown |
| `base/api-service.yaml`, `frontend-service.yaml` | ClusterIP Services |
| `base/hpa.yaml`, `pdb.yaml` | autoscaling 2–6; disruption budget |
| `base/network-policy.yaml` | default deny + minimal allows |
| `overlays/local/` | demo mode, local images |
| `overlays/gke/` | prod env, Artifact Registry images, Secret Manager CSI, Ingress, BackendConfig, optional managed cert |

## CI/CD: `.github/workflows/`
`ci.yml` (lint, tests, demo eval, pip-audit, manifests; main: images, smoke test, Trivy) · `deploy.yml` (WIF →
Artifact Registry → GKE, rollback) · `eval-live.yml` (manual live evaluation).

## Tests: `tests/`
`unit/` (schemas, rules, prompts, LLM client, grounding, observability, evaluation metrics, container config,
Kubernetes manifests, workflows, production hardening),
`api/` (HTTP behaviour), `integration/` (whole graph with faked providers), `frontend/` (client, presenters,
Streamlit AppTest), `live/` (opt-in real APIs). `fakes.py` holds hand-written fixtures (not recorded API responses).

## Scripts
`scripts/run_research.py`: run research (or `--plan`) from the CLI, live or `--demo`; `--out` saves JSON.
