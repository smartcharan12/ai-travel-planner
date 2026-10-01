# Architecture — AI Travel Planner

> **Status legend** used throughout this repo:
> ✅ built and tested · 🚧 designed, built in a later stage · 📝 instructions only (not run by the author)
> **Final status (Stage 5):** all stages built. Application, evaluation logic and observability are VERIFIED by
> 300 offline tests. Docker, Kubernetes, GCP and CI/CD are written and statically validated, NOT RUN.
> Real Gemini/Tavily calls NOT RUN (no keys). See FINAL_PROJECT_REPORT.md.
>
> Build stages: **Stage 1** ✅ foundations · **Stage 2** ✅ research layer (search, Gemini extraction, grounding) ·
> **Stage 3** ✅ itinerary planning, budget, Streamlit UI · **Stage 4** ✅ evaluation, logging, ELK, Docker ·
> **Stage 5** ✅ Kubernetes, GCP, CI/CD, final docs and audit. See §14.

This document is the map of the whole system. Every later file has a place on it. If you only read one design
document, read this one.

---

## 0. Final architecture (Stage 5)

### Cloud target (GCP), DOCUMENTED ONLY

```mermaid
flowchart TB
    GH[GitHub] --> GA[GitHub Actions<br/>ci.yml: lint, tests, demo eval, pip-audit,<br/>kubeconform, build, smoke test, Trivy]
    GA -- deploy.yml via Workload Identity Federation --> AR[(Artifact Registry)]
    AR --> GKE
    subgraph GKE[GKE Autopilot, namespace travel-planner]
      ING[Ingress → Cloud Load Balancer] --> UI[Streamlit<br/>Deployment ×1]
      UI -- ClusterIP --> API[FastAPI<br/>Deployment ×2..6, HPA]
      API --> LG[LangGraph: research → plan → validate ⇄ repair → itinerary + budget]
    end
    LG -- HTTPS --> TAV[(Tavily)] & GEM[(Gemini)]
    SM[(Secret Manager)] -. CSI files, Workload Identity .-> API
    API & UI -- JSON stdout --> CL[Cloud Logging] --> CMON[Cloud Monitoring<br/>log-based metrics, alerts]
    API -. /api/v1/metrics .-> CMON
```

### Local (docker-compose), configuration tested, NOT RUN

```mermaid
flowchart LR
    B[Browser] --> FE[frontend :8501] --> APIc[api :8000]
    APIc -- app.jsonl volume --> LS[Logstash] --> ES[(Elasticsearch)] --> KB[Kibana :5601]
    APIc --> TAVc[(Tavily)] & GEMc[(Gemini)]
```

Local uses ELK; GCP uses Cloud Logging. The app is identical in both: it writes JSON to stdout, plus a file only
when `LOG_FILE` is set (compose).

## 1. The problem

Planning a trip means answering many small questions at once: *what is worth seeing, which areas to stay in,
what to eat given my diet, how to get there, how to fit it into N days, and can I afford it?* The answers depend
on **current** information (prices, closures, new restaurants) and on **personal** preferences that interact
with each other ("relaxed couple trip, vegetarian, beaches and nightlife, ₹25,000 for two").

Today people do this by opening 20 browser tabs and stitching the results together by hand.

**Our system** takes one structured request and returns a day-by-day plan in which every place comes from
current web research, every price says where it came from, and the total cost is calculated by code rather
than guessed.

## 2. Why AI, and why not *only* AI

| Sub-problem | Who does it | Why |
|---|---|---|
| Validate the request (dates, ranges, characters) | **Python / Pydantic** | Hard rules, must be exact |
| Find current places, hotels, transport | **Search API** (Tavily/Serper) | LLM knowledge is frozen at its training date |
| Read messy web snippets and pull out "Fort Aguada, a 17th-century fort in Candolim" | **LLM** | Unstructured language understanding; impossible to write rules for every website |
| Decide which places suit *this* traveller and group them into sensible days | **LLM** | Judgement over many soft, competing preferences |
| Check every scheduled place really came from research | **Python** | Deterministic, cheap, verifiable |
| Remove duplicates, cap activities per day, order by time slot | **Python** | Rules we can state exactly |
| Add up the budget | **Python** | LLMs are unreliable at arithmetic |

**Why a rule-based app can't do it alone.** You could hard-code "Goa → Baga Beach, Fort Aguada" but you would
need a hand-maintained database for every city on Earth, it would go stale, and the rules for "couple who like
food and nightlife, relaxed pace, vegetarian" multiply combinatorially. Reading free web text and making
trade-offs between soft preferences is exactly what LLMs are good at.

**Why an LLM can't do it alone.** Asked "plan 4 days in Goa for ₹25,000", a bare LLM writes a fluent plan with
invented prices, possibly closed restaurants, and sums that don't add up. So we surround the LLM with code that
feeds it facts, constrains its output, checks it, and does the maths.

## 3. Overall architecture

```mermaid
flowchart TD
    U([User]) --> FE[Streamlit frontend<br/>frontend/]
    FE -- "POST /api/v1/plan (JSON)" --> API[FastAPI backend<br/>app/api/]
    API -- TravelRequest --> WF[LangGraph planning workflow<br/>app/graph/]

    subgraph WF_INNER [Planning workflow]
      direction TB
      R[Research nodes<br/>5 searches in parallel] --> X[Extract entities<br/>LLM call #1]
      X --> G[Generate itinerary<br/>LLM call #2]
      G --> O[Optimize<br/>deterministic]
      O --> V{Validate<br/>deterministic}
      V -- errors --> RP[Repair<br/>LLM call] --> O
      V -- ok --> B[Budget engine<br/>deterministic]
      B --> Q[Quality checks<br/>deterministic]
    end

    WF --- WF_INNER
    R <--> S[(Search API<br/>Tavily / Serper)]
    X <--> L[(Gemini LLM)]
    G <--> L
    RP <--> L

    API -- TravelResponse --> FE
    API -. JSON logs .-> LOG[stdout + log file]
    LOG -.-> ELK[Logstash → Elasticsearch → Kibana]
    EVAL[DeepEval offline evaluation<br/>evaluation/] -. calls .-> API
```

**How to read it:** solid arrows are the request path; dotted arrows are observability and evaluation, which
watch the system but never sit in the user's path. The user waits only for the solid path.

## 4. Where each technology is used (answers to the design questions)

**Q4 — Where exactly is the LLM used?** Three places, all in the workflow, never in the API layer:
1. *Entity extraction* (`research_prompt`, temperature 0): turn search snippets into typed `Attraction`,
   `Restaurant`, `Hotel`, `Transportation` objects, each citing its source.
2. *Itinerary generation* (`planner_prompt`, temperature 0.3): choose and arrange places into days.
3. *Repair* (`repair_prompt`), only when validation fails: fix the listed problems.

**Q5 — Where is LangChain used?** Only where it saves real work:
- `ChatGoogleGenerativeAI`: one interface to Gemini; swapping provider = changing one factory function.
- `ChatPromptTemplate`: prompts as reviewable templates with named variables.
- `.with_structured_output(PydanticModel)`: makes the model return JSON matching our schema, and parses it.
- Token-usage metadata on responses, used for cost tracking.

We do **not** use LangChain's search tool wrappers or agents: our own `SearchProvider` classes are about 60
lines, easier to test, and give us control over timeouts and error mapping.

**Q6 — Where is LangGraph used?** To run the workflow in §5: parallel research branches, a conditional
validate → repair loop with a bounded retry count, and one typed `PlannerState` passed between steps. Without it
we would hand-write the fan-out, the loop and the state bookkeeping.

**Q7 — Where are tools used?** The five research functions (destination, attractions, restaurants, hotels,
transport) are our "tools". We call them deterministically, in parallel, every time. We do *not* let the LLM
decide whether to search (classic agent tool-calling), because a travel plan always needs all five, and
skipping a search is exactly how hallucinations get in. See §6 for this trade-off.

**Q8 — Where does real-time search happen?** In the research nodes, through `app/tools/search/`. That is the
*only* place the system touches the live web.

**Q9 — How is information passed between components?** Always as Pydantic models (typed, validated objects),
never as loose dicts or raw strings:
`TravelRequest → SearchHit[] → ResearchResult → Itinerary → BudgetBreakdown + QualityReport → TravelResponse`.
Inside the workflow these sit as fields of one `PlannerState` object.

**Q10 — How is the itinerary generated?** The LLM receives the user's request plus a numbered list of
researched places (`A1 Fort Aguada — Candolim — [S3]`, …) and must return an `Itinerary` in which every activity
references a place id from that list (or `null` for generic items such as "free time at the beach").

**Q11 — How do we reduce hallucinations?** (Never "prevent": no technique gets that to zero.)

| Technique | What it stops |
|---|---|
| Real-time search before generation | Outdated or imagined places |
| Extracted entities must cite a source; name must appear in that source's text | Invented places in the research step |
| Planner may only use place ids from research | Invented places in the itinerary |
| Structured output + `extra="forbid"` schemas | Free-form text, invented fields like `opening_hours` |
| `cost_basis` (`source` / `estimate` / `unknown`) on every price | Confidently invented prices |
| Time slots (morning/afternoon/evening) instead of clock times | Invented opening hours and timings |
| `uncertainty_notes` field | Model guessing instead of saying "unverified" |
| Deterministic validation + bounded repair loop | Plans that break hard rules reaching the user |
| Budget computed in Python | Arithmetic mistakes |
| Sources returned to the user | Unverifiable claims |

**Q12 — How do we validate the itinerary?** Three layers: (1) Pydantic schema validation of the LLM's JSON;
(2) deterministic business rules: correct number of days, known place ids, no duplicate attractions, activity
cap per pace, slot ordering; (3) quality signals: share of grounded activities, share of sourced prices.
Errors trigger repair; warnings are shown to the user.

**Q13 — How is it monitored?** Every request gets a `request_id`. Each request writes one structured JSON log
line (plus lines for each LLM and search call) with latency, status, model, tokens and error code. `/metrics`
shows live per-process counters. ELK stores the logs and draws dashboards (see §8).

**Q14 — How is the LLM evaluated?** Offline, with DeepEval: a dataset of realistic requests runs through the
real pipeline, and metrics score faithfulness to the retrieved research, relevance to the request, and
constraint adherence (days, diet, budget). Online, every response carries the cheap deterministic
`QualityReport`.

**Q15–17 — Deployment, Kubernetes, GCP.** See §9.

**Q18 — Why ELK?** Logs from several pods and the frontend must be searchable in one place, and must survive
pod restarts. ELK is open source, runs locally in Docker for learning, and Kibana gives dashboards without
writing code. On GCP we would normally use Cloud Logging (built into GKE). We keep ELK for local work and
document both, because both appear in job descriptions and the concepts transfer.

**Q19 — Why DeepEval?** Unit tests check *code* ("does the budget add up?"). They cannot check *language*
("is this plan faithful to the sources and useful?"). DeepEval provides LLM-as-judge metrics (faithfulness,
relevancy, custom G-Eval criteria) inside a pytest-like workflow, so evaluation runs like a test suite.

## 5. The LangGraph workflow ✅ (research: Stage 2 · itinerary: Stage 3)

Node names below are the real ones from `app/graph/research_graph.py` and `planning_graph.py`; the research part is explained in detail
in `docs/09_research_pipeline.md`, the itinerary part in `docs/13_itinerary_planning.md` and
`docs/14_validation_and_repair.md`.

```mermaid
flowchart TD
    START([START]) --> VI[prepare_queries ✅<br/>5 deterministic queries]
    VI --> S1[search_destination ✅]
    VI --> S2[search_attractions ✅]
    VI --> S3[search_restaurants ✅]
    VI --> S4[search_hotels ✅]
    VI --> S5[search_transportation ✅]
    S1 & S2 & S3 & S4 & S5 --> AG[aggregate_research ✅<br/>dedupe URLs, filter irrelevant, number sources S1..Sn]
    AG -- "no usable results" --> FAIL([END: NO_RESEARCH_RESULTS])
    AG --> EX[extract_entities ✅<br/>LLM #1, temperature 0]
    EX --> GR[ground_entities ✅<br/>drop entities whose name is not in cited source]
    GR --> CR{check_research ✅<br/>any attractions/restaurants?}
    CR -- no --> FAIL3([END: NO_RESEARCH_RESULTS])
    CR --> GEN[generate_itinerary ✅<br/>LLM #2, temperature 0.3]
    GEN --> OPT[optimize_itinerary ✅<br/>order slots, dedupe, caps]
    OPT --> VAL{validate_itinerary}
    VAL -- "errors and attempts < MAX_REPAIR_ATTEMPTS" --> REP[repair_itinerary<br/>LLM, given the error list]
    REP --> OPT
    VAL -- "errors and attempts exhausted" --> FAIL2([END: ITINERARY_INVALID])
    VAL -- "ok (warnings allowed)" --> ASM[assemble_itinerary ✅<br/>dates, areas, verified prices]
    ASM --> BUD[calculate_budget ✅<br/>deterministic]
    BUD --> QC[quality_check ✅<br/>deterministic]
    QC --> END([END: TravelResponse])
```

**State passed between nodes** (`PlannerState`, one object that each node reads and adds to):

| Field | Written by | Read by |
|---|---|---|
| `request: TravelRequest` | API | every node |
| `category_results` | search nodes (merged with a reducer, because they run in parallel) | aggregate |
| `hits: list[SearchHit]` | aggregate | extract, ground |
| `research: ResearchResult` | aggregate, extract, ground | generate, validate, budget, quality |
| `draft: ItineraryDraft` | generate, repair, optimize | validate, repair, assemble |
| `itinerary: Itinerary` | assemble | budget, quality, response |
| `issues: list[ValidationIssue]` | validate | router, repair, response |
| `repair_attempts: int` | repair | router |
| `budget: BudgetBreakdown` | budget | response |
| `usage` (LLM calls, tokens, latencies) | LLM and search nodes | response metadata, logs |

**Partial failure policy.** If one search category fails (say hotels time out), the plan continues with a
warning and `status: "partial"`. If *all* searches return nothing usable, we stop with `NO_RESEARCH_RESULTS`
rather than letting the LLM fill the gap from memory.

## 6. Agent or workflow? (an important design choice)

An **agent** lets the LLM decide its next step in a loop ("should I search hotels now?"). A **workflow** fixes
the steps in code and uses the LLM inside specific steps.

We chose a **workflow with one agentic element** (the self-correcting validate → repair loop) because:
- every trip needs the same five kinds of research, so there is nothing for the LLM to decide there;
- fixed steps mean predictable cost (2–4 LLM calls, exactly 5 searches) and latency;
- each step can be unit-tested on its own;
- an LLM choosing to skip a search is a direct path to hallucination.

A free-roaming agent would make sense for open-ended follow-ups ("find a cheaper hotel near day 2's
activities"). That is listed as a future improvement, not built.

## 7. Search architecture ✅ (Stage 2, see `docs/07_search_layer.md`)

```mermaid
classDiagram
    class SearchProvider {
        <<abstract>>
        +name: str
        +search(query, category, max_results) list~SearchHit~
    }
    SearchProvider <|-- TavilySearchProvider
    SearchProvider <|-- SerperSearchProvider
    SearchProvider <|-- DemoSearchProvider
    class TavilySearchProvider { POST api.tavily.com/search }
    class SerperSearchProvider { POST google.serper.dev/search }
    class DemoSearchProvider { invented, labelled offline data; DEMO_MODE only }
    ResearchNodes --> SearchProvider : uses (chosen by SEARCH_PROVIDER)
```

Each provider converts its own response format into the same `SearchHit` model and maps HTTP failures to
our exceptions (timeout → `SearchTimeoutError`, 429 → `RateLimitError`, other errors → `SearchProviderError`).
The rest of the system never knows which provider ran.

**What needs live search vs. what the LLM may supply:** places, hotels, restaurants, prices, transport options
and seasonal notes need search. General phrasing, grouping and travel-style advice ("carry sunscreen") may come
from the LLM and are labelled as tips, not facts.

## 8. Observability architecture ✅ code · 📝 ELK not run (Stage 4: see docs/18, docs/20)

```mermaid
flowchart LR
    APP[FastAPI app<br/>JSON events: request_completed, search_call,<br/>llm_call, itinerary_validated, plan_completed…] --> OUT[stdout]
    APP --> FILE[/var/log/app/app.jsonl<br/>shared Docker volume/]
    FILE --> LS[Logstash<br/>parse, enrich, drop secrets]
    LS --> ES[(Elasticsearch<br/>index: travel-planner-logs-*)]
    ES --> KB[Kibana<br/>dashboards & search]
    OUT --> CL[Cloud Logging<br/>on GKE, automatic]
```

- **Application monitoring**: is the service healthy? Request rate, error rate, HTTP latency, pod restarts.
- **LLM observability**: is the AI part behaving and affordable? LLM latency per call, calls per request,
  input/output tokens, estimated cost, repair-loop frequency, grounding ratio, search failures by provider.

Both come from the same structured log lines. What differs is which fields you chart. Every event of a request
carries the same `request_id` (log correlation; no distributed tracing system yet). Metrics: `/api/v1/metrics`.
Offline LLM evaluation (DeepEval + deterministic metrics) lives in `evaluation/` (docs/19).

## 9. Deployment architecture (Docker, Kubernetes ✅ written and statically validated · 📝 not run; GCP 📝 documented, see docs/21–24)

```mermaid
flowchart LR
    CODE[Source code] --> IMG[Docker image<br/>Dockerfile]
    IMG --> AR[Artifact Registry<br/>GCP image store]
    AR --> GKE[GKE cluster]
    subgraph GKE
      direction TB
      ING[Load balancer / Ingress] --> FESVC[frontend Service] --> FEPOD[frontend pods]
      FEPOD --> APISVC[api Service] --> APIPOD[api pods ×2<br/>liveness + readiness probes]
      CM[ConfigMap<br/>non-secret settings] -.-> APIPOD
      SEC[Secret Manager files via CSI<br/>Workload Identity, no key files] -.-> APIPOD
    end
    APIPOD --> GEM[(Gemini API)]
    APIPOD --> TAV[(Tavily API)]
```

- **Docker** packages the app and its exact dependencies into an image that runs identically everywhere.
- **Kubernetes** runs several copies (replicas) of that image, restarts crashed ones, routes traffic only to
  ready ones (readiness probe = `/api/v1/health/ready`), and rolls out new versions without downtime.
- **GCP** provides managed Kubernetes (GKE) so we don't run control-plane servers ourselves, a private image
  registry (Artifact Registry), secret storage (Secret Manager), and log collection (Cloud Logging). GCP also
  fits naturally with Gemini, but nothing in the code depends on GCP: the same image runs on any Kubernetes.

The service is **stateless**: no database, and each request is independent. That is what makes horizontal
scaling simply "add replicas". Long-running work (30–60 s per plan, dominated by LLM latency) is the main
scaling concern, which is why timeouts and bounded retries are configuration, not hard-coded.

## 10. CI/CD ✅ written, actionlint clean · NOT RUN on GitHub (docs/26)

```mermaid
flowchart LR
    P[PR / push] --> T[ruff + pytest + demo eval] & DA[pip-audit] & M[kustomize + kubeconform]
    T -- main only --> I[hadolint, build images, smoke test, Trivy]
    I -. CI success on main .-> D[deploy.yml: WIF → Artifact Registry → kubectl apply -k → rollout / undo]
    MAN[manual] --> L[eval-live.yml: live tests + DeepEval]
```

## 11. Technology decisions

| Technology | Decision | Reason | What we'd lose without it |
|---|---|---|---|
| Python 3.11+ | ✅ | AI ecosystem, your existing skill | — |
| FastAPI | ✅ | Typed request/response from Pydantic, automatic `/docs`, async-ready | Hand-written validation and docs |
| Pydantic v2 | ✅ | One schema serves API validation, LLM structured output and docs | Three diverging definitions of "an itinerary" |
| pydantic-settings | ✅ | Typed env-var config, secrets masked | Scattered `os.getenv`, string-typed config bugs |
| Gemini (via LangChain) | ✅ (offline-verified; live call NOT TESTED, key required) | Good structured output, free tier, natural fit with GCP | — (provider is swappable) |
| LangChain (core pieces only) | ✅ | Provider-neutral chat model, prompt templates, structured output | Re-implementing parsing/retries per provider |
| LangGraph | ✅ research graph | Parallel branches, conditional repair loop, typed shared state | Hand-rolled orchestration |
| Tavily (default) / Serper | ✅ (HTTP mocked in tests; live call NOT TESTED, key required) | Tavily returns page extracts made for LLMs; Serper returns Google results cheaply | Stale LLM memory |
| Streamlit | ✅ | Pure-Python UI; talks to the API over HTTP like any client | A JS toolchain to learn |
| pytest + ruff | ✅ | Standard testing and linting | Regressions, style drift |
| DeepEval | ✅ (demo run; live/judge NOT RUN: keys) | LLM-as-judge metrics in a test-like workflow | No measure of answer quality |
| Docker / Compose | ✅ written, statically tested; NOT RUN (Docker unavailable) | Reproducible runtime; local ELK in one command | "Works on my machine" |
| Kubernetes | ✅ manifests (kubeconform 31/31); cluster NOT RUN | Replicas, self-healing, probes, rolling updates | Manual restarts and scaling |
| GCP (GKE, Artifact Registry, Secret Manager, Cloud Logging) | 📝 | Managed versions of the above | Running our own infrastructure |
| ELK | ✅ written, statically tested; NOT RUN (Docker unavailable) | Central, searchable logs and dashboards | Grepping logs pod by pod |
| GitHub Actions | ✅ written (actionlint clean); NOT RUN | Tests on every push, build images | Broken main branch |

**Deliberately *not* used, and why:**

- **Vector database / embeddings RAG.** RAG means *retrieve relevant text, then generate using it*. We do
  exactly that, but our retriever is a live web search, because travel facts change and we have no private
  document collection to index. A vector DB would add cost and staleness for no gain here. (`docs/10_rag.md`
  explains RAG fully and where a vector DB *would* fit, e.g. caching past research.)
- **Database.** The service is stateless; nothing must persist between requests. Adding Postgres just to look
  bigger would break the "every technology has a reason" rule. Saving trips would be the trigger to add one.
- **React.** Streamlit keeps the whole project in one language while you learn. The API is frontend-agnostic.
- **Celery/queues, Redis cache.** Sensible at higher traffic. Listed as future improvements.

## 12. Folder structure (target)

```text
ai-travel-planner/
├── README.md                 ✅ entry point, status, how to run
├── ARCHITECTURE.md           ✅ this file
├── pyproject.toml            ✅ project metadata, ruff + pytest config
├── requirements.txt          ✅ pinned runtime deps
├── requirements-dev.txt      ✅ + test/lint tools
├── .env.example              ✅ every setting, no real values
├── app/
│   ├── main.py               ✅ FastAPI app factory
│   ├── config.py             ✅ typed settings from env vars
│   ├── core/exceptions.py    ✅ domain errors → HTTP status codes
│   ├── api/                  ✅ routes, middleware (request id, metrics), error handlers
│   ├── schemas/              ✅ all Pydantic contracts (request, research, itinerary, response)
│   ├── observability/        ✅ JSON logging, request context, metrics registry
│   ├── llm/                  ✅ factory, StructuredLLM (parse/validate/retry/errors/usage), demo model
│   ├── prompts/              ✅ research, planner and repair prompts
│   ├── tools/search/         ✅ SearchProvider base + Tavily, Serper, Demo, factory
│   ├── research/             ✅ queries, normalizer, grounding, text helpers
│   ├── graph/                ✅ state, research graph, planning graph
│   ├── planning/             ✅ optimizer, validator, assembler, pricing, budget engine, quality
│   ├── services/             ✅ TravelPlanner (/plan), ResearchPlanner (/research)
│   └── demo/                 ✅ invented, labelled offline data (DEMO_MODE)
├── scripts/run_research.py   ✅ run the research workflow from the CLI
├── frontend/                 ✅ Streamlit app, API client, presenters
├── tests/                    ✅ unit/ api/ integration/ (offline) · live/ (optional, real APIs)
├── evaluation/               ✅ DeepEval dataset, metrics, judge, runner, suites
├── Dockerfile                ✅ API image · frontend/Dockerfile ✅ UI image · .dockerignore ✅
├── docker-compose.yml        ✅ api + frontend; --profile elk adds ES, Logstash, Kibana
├── infrastructure/
│   └── kubernetes/           ✅ base + overlays/local + overlays/gke (kustomize)
├── monitoring/elk/           ✅ Logstash pipeline, ES index template, Kibana setup
├── docs/                     learning docs (numbered) + REQUEST_FLOW, FILE_GUIDE, etc.
└── .github/workflows/        ✅ ci.yml, deploy.yml, eval-live.yml
```

**Changes from the originally suggested structure, and why:**

| Suggested | Ours | Reason |
|---|---|---|
| `app/models/` **and** `app/schemas/` | `app/schemas/` only | We have no database models; two folders for the same thing would confuse. |
| `app/agents/` + `app/chains/` | `app/graph/` + `app/llm/` | The orchestration is a LangGraph *graph* (see §6), and "chains" would be 3 lines each, so they live beside the prompts they use. |
| `app/logging/` | `app/observability/` | A package called `logging` shadows Python's built-in `logging` module and causes confusing import bugs. |
| `app/evaluation/` + `evaluation/` | `evaluation/` only | Evaluation is offline tooling, not part of the running service image. |
| `budget_prompt.py`, `validation_prompt.py` | `repair_prompt.py` | Budget and validation are deterministic code (on purpose), so they need no prompt. Repair is the LLM step that reacts to validation. |
| `docs/12_database.md` | `docs/12_data_models.md` | No database (see §11); the data models deserve that chapter instead. |
| `app/core/` | added | Shared exceptions used by every layer, kept free of FastAPI imports. |
| — | `app/research/` (Stage 2) | Query building, normalization and grounding are plain-Python research logic, testable without LangGraph or an LLM. |
| — | `app/demo/` (Stage 2) | Keeps invented demo data in one obvious place, far from real code paths. |
| `app/services/` for budget/optimizer | `app/planning/` (Stage 3) | Pure deterministic planning rules, separate from the service classes that orchestrate the graph. |
| `infrastructure/docker/` | root `Dockerfile` + `frontend/Dockerfile` (Stage 4) | Docker's default location and build context is the repo root; compose builds both from there. |
| `infrastructure/gcp/` | `docs/24_gcp.md` + `overlays/gke/` | GCP setup is a sequence of one-time `gcloud` commands, better as a documented guide than unexecuted scripts; GKE-specific YAML lives in the overlay. |
| — | `POST /api/v1/research` (Stage 3) | Keeps the Stage 2 research-only response available for inspecting research quality. |
| `docs/11_api.md` | `docs/05_api.md` | Number 11 is now the request-to-research walkthrough; the API is Phase 5. |

## 13. End-to-end data flow (the running example)

User: **Goa, 4 days, ₹25,000 total, 2 travellers, couple, interests beaches/food/nightlife, from Bengaluru.**

1. **Frontend** collects the form and sends JSON to `POST /api/v1/plan`.
2. **API** (`app/api/routes.py`) has FastAPI parse it into `TravelRequest`. Bad input → 422, and no money is
   spent. Middleware assigns `request_id`.
3. **Workflow** starts with `PlannerState(request=...)`.
4. **Five searches run in parallel**: e.g. `"best beaches and attractions in Goa for couples food nightlife"`.
   Each returns `SearchHit`s; results are deduplicated and numbered `S1..Sn`.
5. **Extraction LLM** turns snippets into `A1 Baga Beach [S2]`, `R3 … [S5]`, `H1 … [S7]`. Entities whose name
   does not appear in their cited snippet are dropped.
6. **Planner LLM** builds 4 `DailyPlan`s referencing those ids, prices tagged with `cost_basis`.
7. **Optimizer** removes duplicates, enforces ≤ 4 activities/day (moderate pace), orders slots.
8. **Validator** checks ids, day count and duplicates → repair loop if needed.
9. **Budget engine** sums sourced prices and fills gaps with labelled heuristics → `BudgetBreakdown`
   (total, remaining, within_budget, assumptions).
10. **Quality check** computes grounding ratios → `QualityReport`.
11. **API** returns `TravelResponse`. One JSON log line records request id, destination, latency, model,
    tokens, status.
12. **Logstash** ships the line to **Elasticsearch**; **Kibana** charts it. **DeepEval** later replays
    requests like this one offline and scores the output.

`docs/11_request_to_research_flow.md` shows the JSON at each research step; `docs/REQUEST_FLOW.md` continues
through planning, repair, budget and response.

## 14. Roadmap

The original plan had itinerary generation in Stage 2. In Stage 2 we chose to finish the research layer
first (search → extraction → verification), so itinerary generation moved to Stage 3 and the later stages shift.

| Stage | Contents | Status |
|---|---|---|
| **1** | Architecture, structure, config, data models, FastAPI | ✅ |
| **2** | Search abstraction + Tavily/Serper, deterministic queries, normalization, Gemini integration, research prompt, extraction, grounding/traceability, demo mode, `/plan` returns research | ✅ (live APIs NOT TESTED: keys required) |
| **3** | Itinerary generation (planner prompt), optimizer, validation + repair loop, budget engine, `TravelResponse`, Streamlit frontend | ✅ (live APIs NOT TESTED: keys required) |
| **4** | Grounding fix (no LLM titles, named-place check), DeepEval evaluation, structured JSON logging, LLM/search/repair observability, ELK, Docker / docker-compose | ✅ (live eval, judge, Docker, ELK NOT RUN: see README) |
| **5** | Kubernetes (kustomize), GCP guide, CI/CD, hardening (CORS, limits, prod guard, file secrets), final docs and audit | ✅ (Docker/K8s/GCP/CI NOT RUN; see FINAL_PROJECT_REPORT.md) |
