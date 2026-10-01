# Final Project Report — AI Travel Planner (LLMOps)

Status labels used throughout: **VERIFIED** (run and checked here) · **NOT VERIFIED** · **NOT RUN** ·
**DOCUMENTED ONLY** · **DEMO ONLY** (offline invented data) · **REAL API** · **LOCAL ONLY** · **CLOUD VERIFIED**.
Nothing in this report is **REAL API** or **CLOUD VERIFIED**: no API keys, Docker, Kubernetes or GCP access were
available on the build machine.

## Executive summary
A travel itinerary planner that researches a destination on the live web, extracts places with Gemini, verifies
every place and price against its source, plans days using only verified places, checks and repairs the plan
with code, and computes the budget deterministically. Around it: JSON observability, an offline DeepEval
evaluation suite, Docker/compose with ELK, Kubernetes manifests, a GCP deployment design, and GitHub Actions
CI/CD. **300 offline tests pass.** The core pipeline is verified end to end in demo mode and with faked
providers. The real Gemini/Tavily path, containers, cluster and cloud are built, statically validated and
documented, but **not executed**.

## Problem
Trip planning combines changing facts (places, prices, transport) with personal preferences. A chatbot answers
fluently but invents places and prices, because its knowledge is frozen and it optimises for plausibility, not truth.

## Solution
Split the work: **code** for validation, verification, arithmetic and rules; **live search** for facts; **the LLM**
only for reading web text and for judgement (which places suit this traveller, how to group days). Every number
and place in the output is traceable to a source, or explicitly labelled as an estimate or unknown.

## Architecture
See [ARCHITECTURE.md](ARCHITECTURE.md) (cloud and local diagrams). In one line:
Streamlit → FastAPI → LangGraph [5 parallel Tavily searches → Gemini extraction → grounding → Gemini planning →
optimizer → validator ⇄ bounded Gemini repair → assembler → budget → quality] → response, with JSON events to
stdout (→ Cloud Logging on GKE, → Logstash/Elasticsearch/Kibana locally).

## Technology decisions (each has a reason)

| Technology | Why it's here | What it replaced or avoided |
|---|---|---|
| FastAPI + Pydantic | typed contracts shared by API, LLM output and docs | hand-written validation |
| Gemini via LangChain core | structured JSON output; provider-neutral interface; free tier | provider-specific code |
| LangGraph | parallel search, typed state, bounded repair loop | hand-rolled orchestration |
| Tavily (Serper alternative) | page extracts made for LLMs | stale model memory |
| Streamlit | Python-only UI | a JS toolchain |
| DeepEval | metrics and thresholds for LLM output; custom deterministic metrics | eyeballing outputs |
| JSON logs + in-process metrics | queryable events, request correlation | grep |
| ELK (local) / Cloud Logging (GCP) | central search; managed in the cloud | running ELK on GKE (avoided on purpose) |
| Docker, Kubernetes, GKE Autopilot | reproducible images; replicas, probes, autoscaling; managed nodes | hand-managed VMs |
| Secret Manager + Workload Identity | no key files anywhere | JSON service-account keys |
| GitHub Actions | CI on every PR, gated deploys, manual live eval | manual releases |
| **Not used:** vector DB, database, Redis, queues, React, service mesh | no requirement justified them (stateless service, live retrieval) | — |

## End-to-end flow
[docs/FINAL_REQUEST_FLOW.md](docs/FINAL_REQUEST_FLOW.md) traces one Goa request from browser to Cloud Logging;
[docs/REQUEST_FLOW.md](docs/REQUEST_FLOW.md) shows the JSON at each step.

## LLM design
Three LLM jobs, all through `StructuredLLM`: **extraction** (temperature 0), **planning** (0.3), **repair**
(0.3, only on validation errors). Each call has a JSON schema bound to Gemini (`response_json_schema`),
Pydantic re-validation, one bounded output retry with error feedback, a hard timeout, error mapping to domain
errors, and an `llm_call` log with tokens and cost (when known). The LLM never computes prices, dates, titles or totals.

## Grounding strategy
1. Fixed queries, live search; no results → stop before any LLM call.
2. Normalised, numbered sources; web text delimited and treated as untrusted.
3. Extracted entities must cite a returned source **and** their name must appear in it; prices must be quoted
   verbatim and match the amount.
4. The planner references entities only by verified id, or uses an explicit `generic_kind`; titles are generated
   by code; free text is checked for capitalised place names absent from verified research.
5. Sources returned to the user. Known limits: lower-case names are undetected; a malicious page can promote a place it mentions.

## Validation
Deterministic rules: day count, empty days, unknown ids, hotel used as an activity, place-or-generic, unsupported
named places, pace and slot caps (errors); dietary unverified, no hotel, low grounding, backtracking (warnings).

## Repair
Errors → repair prompt with the previous draft and the exact problem list → optimizer → validator again, at most
`MAX_REPAIR_ATTEMPTS` (2) times → otherwise `ITINERARY_INVALID` (502). Measured by `itinerary_first_draft_total`,
`repair_success_total`, `itinerary_invalid_total`.

## Budget
Pure Python: verified source prices first; labelled developer defaults (INR only) otherwise; unknown costs are
flagged (`complete: false`), never guessed; every line shows its calculation; overspend raises `OVER_BUDGET`.

## Evaluation
10 fixed cases (Goa, Hyderabad, Jaipur, Delhi, Bengaluru; five travel styles). 7 deterministic metrics + 4
LLM-judge metrics (Faithfulness, coherence, preference alignment, usefulness). INITIAL ENGINEERING THRESHOLDS.
- **DEMO ONLY, VERIFIED:** runner 8/10 cases pass all metrics; grounding, unsupported-place, completeness,
  budget and constraint metrics 1.00 on all 10; `preference_match` 0.85 mean, correctly failing two cases
  whose interests have no demo places. `deepeval test run evaluation/test_research.py`: 10/10.
- **Live evaluation and LLM judge: NOT RUN** (no keys).

## Observability
JSON events per step sharing `request_id` (`search_call`, `llm_call`, `itinerary_validated`, `plan_completed`,
`request_completed`…), with a `severity` field for Cloud Logging. Metrics for calls, latency, tokens, repairs,
budget, rate limiting. **VERIFIED locally** (log file contents, metrics endpoint). No distributed tracing.

## Docker
Multi-stage, non-root (numeric uid 10001), healthchecked API and UI images; compose with an optional ELK profile.
hadolint clean (**VERIFIED**). **Build and run: NOT RUN** (Docker not installed).

## Kubernetes
Base + local + GKE overlays: 2–6 API replicas (HPA), probes, PDB, security contexts, read-only root FS,
NetworkPolicies, ClusterIP-only API, Ingress for the UI. **VERIFIED statically** (kustomize render; kubeconform
strict 31/31; 16 consistency tests). **Cluster deployment: NOT RUN.**

## GCP
GKE Autopilot, Artifact Registry, Secret Manager (CSI files via `SECRETS_DIR`), Workload Identity for pods and
CI, Cloud Logging/Monitoring, optional Cloud Armor. **DOCUMENTED ONLY** ([docs/24_gcp.md](docs/24_gcp.md)).

## CI/CD
`ci.yml` (lint, tests, demo eval, pip-audit, manifest validation; on main: image builds, smoke test, Trivy),
`deploy.yml` (after CI, WIF, rollout with undo), `eval-live.yml` (manual). actionlint clean and inputs checked
(**VERIFIED**); **never executed on GitHub (NOT RUN)**.

## Security
See [docs/25_security.md](docs/25_security.md). VERIFIED: input validation, injection controls, error hygiene,
log redaction, CORS policy, rate/concurrency limits, prod configuration guard, gitleaks (0 project findings),
pip-audit (no known vulnerabilities), hadolint. NOT RUN: Trivy image scan, cluster security behaviour. GAP: no
end-user authentication; per-process rate limits.

## Testing (exact final audit, 2026-10-02)

| Check | Command | Result | Label |
|---|---|---|---|
| Tests | `pytest -q` | **300 passed, 3 skipped** (unit 246, api 26, integration 15, frontend 13; live 3 skipped: no keys) | VERIFIED |
| Lint / format | `ruff check .` / `ruff format --check .` | pass / 153 files formatted | VERIFIED |
| Imports / deps | import all 72 modules / `pip check` | OK / no broken requirements | VERIFIED |
| API, no keys | live uvicorn | health 200, ready 503, plan/research 503 `CONFIGURATION_ERROR`, invalid body 422, docs 200; fake key found 0 times in logs | VERIFIED |
| API, demo | live uvicorn | ready 200, research 200, plan 200 (repairs 1, 3 LLM calls, `OVER_BUDGET`), rate limit → 429 + `Retry-After: 60`, metrics updated, JSON logs with `severity`, 0 tracebacks | VERIFIED, DEMO ONLY |
| UI | Streamlit + headless Chromium | form, itinerary, budget tab render; screenshots in `docs/images/` | VERIFIED, DEMO ONLY |
| Evaluation | `evaluation.runner --mode demo` | 8/10 cases pass all metrics (exit 1 by design; `--report-only` exit 0) | VERIFIED, DEMO ONLY |
| DeepEval CLI | `deepeval test run evaluation/test_research.py` | 10/10 passed, token cost None | VERIFIED, DEMO ONLY |
| Live tests / live eval / judge | `pytest tests/live`, `--mode live --judge` | skipped / refused without keys | NOT RUN |
| Kubernetes manifests | kustomize v5.8.2 + kubeconform v0.8.0 strict, K8s 1.33 | local 14/14, gke 17/17 valid | VERIFIED (static) |
| Kubernetes cluster | kind / GKE | — | NOT RUN |
| Workflows | actionlint v1.7.12 + input checks | no problems | VERIFIED (static); NOT RUN on GitHub |
| Dockerfiles | hadolint v2.15.1 | clean (after fixing DL3045, DL3066) | VERIFIED (static) |
| Docker build / compose / ELK | `docker compose --profile elk up --build` | — | NOT RUN (Docker not installed) |
| Dependency scan | pip-audit 2.10.1 | no known vulnerabilities | VERIFIED |
| Secret scan | gitleaks 8.30.1 | 0 findings in project files (2 in `.venv` third-party fixtures) | VERIFIED |
| Image scan | Trivy (CI) | — | NOT RUN (needs built images) |
| Docs | link check over 38 markdown files | 0 broken links | VERIFIED |

## Failure behaviour (VERIFIED with faked providers through the real API, 2026-10-02)

| # | Scenario | User sees | Logged | Metrics |
|---|---|---|---|---|
| 1 | Missing Gemini key | 503 `CONFIGURATION_ERROR`, `details.missing=["GEMINI_API_KEY"]` | `request_failed`, `request_completed` (ERROR) | `http_requests_total{status=503}` |
| 2 | Missing Tavily key | 503, `missing=["TAVILY_API_KEY"]` | same | same |
| 3a | All searches time out | 504 `SEARCH_TIMEOUT` | `search_call` ×5 (WARNING), `request_failed` | `search_calls_total{outcome=error}` |
| 3b | One search times out | 200, `status: partial`, warning "hotels search failed (SEARCH_TIMEOUT)" | `search_call` WARNING for hotels | `search_calls_total{category=hotels,outcome=error}` |
| 4 | Search auth failure | 502 `SEARCH_PROVIDER_AUTH_ERROR` | `request_failed` | `search_calls_total{outcome=error}` |
| 5 | Gemini rate limited | 429 `RATE_LIMITED` + Retry-After when known | `llm_call` outcome `rate_limited` | `llm_calls_total{outcome=rate_limited}` |
| 6 | Invalid LLM output twice | 502 `LLM_INVALID_OUTPUT` | 2× `llm_call` `invalid_output` | `llm_calls_total{outcome=invalid_output}` +2 |
| 7 | Invalid draft, repaired | 200, `repair_attempts: 1` | `itinerary_validated` (fail) → `itinerary_repair_requested` → `itinerary_validated` (pass) | `itinerary_first_draft_total{result=invalid}`, `repair_success_total` |
| 8 | Repair fails twice | 502 `ITINERARY_INVALID`, error codes in details | `itinerary_invalid` (ERROR) | `repair_attempts_total` +2, `itinerary_invalid_total` |
| 9 | Budget overflow | 200 with `OVER_BUDGET` warning (and `BUDGET_INCOMPLETE` if costs unknown) | `plan_completed` `within_budget=false` | `budget_overflow_total` |
| 10 | API unavailable (UI) | "Cannot reach the planner API…" + code `API_UNREACHABLE` | — (UI side) | — (VERIFIED in tests/frontend) |
| 11 | Kubernetes pod crash | other replica keeps serving; Deployment recreates the pod; readiness gates traffic | container restart events (`kubectl describe`) | — | **NOT RUN** |
| 12 | Invalid configuration | process refuses to start with a clear validation error (e.g. prod + DEMO_MODE, bad temperature, `*` CORS in prod) | startup error | — (VERIFIED in tests) |

## Performance (what was and wasn't measured)
**Measured (LOCAL ONLY, DEMO ONLY, this laptop):** API startup to healthy 1.6 s; RSS 116 MiB idle, 117 MiB after
30 plans; UI startup 0.9 s, 60 MiB idle; our own pipeline ≈ 30 ms per plan (median 32 ms over 20 demo requests).
**Not measured:** real Tavily and Gemini latency, tokens, cost, container startup, behaviour under load.
**Bottlenecks:** external calls dominate. Expected order: planning call (large JSON output) > extraction call
(large input) > parallel searches (wall time = slowest of 5); repair rounds add a near-full planning call each.
**Scaling:** stateless API → more replicas (HPA); per-replica concurrency cap protects quota; the real ceilings
are Gemini/Tavily rate limits and cost, not CPU. **Cost drivers:** LLM tokens (repairs!), search credits, the load
balancer, logging volume.

## Limitations (not hidden)
- Real Gemini/Tavily never called; real latency, cost and quality unknown.
- Docker, compose, ELK, Kubernetes, GKE, CI/CD never executed.
- Evaluation scores are demo-only; thresholds unvalidated; judge untested.
- Metrics are per process; no distributed tracing.
- Place-name check misses lower-case names; preference metric is a coarse keyword proxy.
- Budget defaults are developer placeholders, INR only.
- No user authentication; rate limits are per replica.
- Streamlit UI is single-replica by design.

## Architecture review (critical)

| Problem | Why it matters | Current mitigation | Future improvement |
|---|---|---|---|
| CPU-based HPA for an I/O-bound service | CPU under-reports load while pods wait on Gemini | concurrency cap returns fast 429s; conservative min 2 | autoscale on in-flight requests / busy-rejections via custom metrics |
| Per-process metrics and rate limits | numbers split across replicas; limits multiply | logs (ELK/Cloud Logging) are the durable view; edge rate limiting documented | Prometheus/Cloud Monitoring metrics; Cloud Armor; shared limiter (Redis) only if needed |
| Two LLM calls before the first result | latency of tens of seconds | progress spinner; parallel searches | stream partial results; cache research per destination |
| Repair repeats a full planning call | doubles cost when it triggers | bounded to 2; metrics show which rules fail | targeted repair of failing days; improve prompt from failure stats |
| Named-place check is heuristic | false negatives (lower case) and positives (capitalised generic phrases) | structural fix (ids, code titles) is primary; detector is secondary; Faithfulness eval | NER-based check, or require all place mentions as ids |
| Budget defaults are invented | budgets for missing prices are rough | labelled `estimate`, listed in assumptions, `sourced_cost_ratio` reported | per-city price research or configurable rate tables |
| Duplicated knowledge across manifests, compose and config | drift (e.g. a ConfigMap key the app ignores) | consistency tests tie them together | generate config docs from `Settings` |
| `evaluation/` and `app/` both define what "grounded" means | could diverge | evaluation reuses app functions (`unsupported_names`, `research_evidence`) | keep reusing; don't fork logic |
| No authentication | anyone with the URL can spend quota | UI-only exposure, rate and concurrency limits | Identity-Aware Proxy or app login |
| ELK and Cloud Logging both documented | two stacks to understand | clear split: local vs cloud; app unchanged | none; this is deliberate |
| Unnecessary components? | — | Serper provider is small and proves the abstraction; ELK is optional; no DB/queue/vector store were added | remove Serper if never used |

## Future improvements (in priority order)
1. Run the real system: live tests, live evaluation with judge, record real latency and cost.
2. Run Docker, kind and the CI pipeline once; fix whatever the first real run reveals.
3. Authentication + Cloud Armor before public exposure.
4. Research cache (per destination, hours); targeted repair; streaming responses.
5. OpenTelemetry tracing; exported metrics; alerting on LLM failure and repair rates.
6. Human-rated evaluation set to calibrate thresholds and the judge.

## Interview explanation
See [docs/FIVE_MINUTE_PROJECT_EXPLANATION.md](docs/FIVE_MINUTE_PROJECT_EXPLANATION.md) and
[INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md).
