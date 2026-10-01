# Final beginner guide: the whole system from zero

For someone who knows basic Python. Each topic: **WHAT** · **WHY** · **HOW** · **WHERE IN CODE** · **EXAMPLE**.
Deeper chapters are linked; the order follows the life of one request, then how it is shipped.

---

### 1. Python application
- **WHAT:** a Python package (`app/`) that runs as a web server.
- **WHY:** Python has the best LLM and data libraries.
- **HOW:** modules by responsibility: `api/` (HTTP), `schemas/` (data), `graph/` (workflow), `planning/` (rules), `llm/`, `tools/`.
- **WHERE:** `app/main.py` → `create_app()`.
- **EXAMPLE:** `uvicorn app.main:app --reload` starts it on port 8000.

### 2. API
- **WHAT:** a program's "menu" of requests other programs can make over HTTP.
- **WHY:** the UI, tests, the evaluation suite and curl all use the same entry point.
- **HOW:** FastAPI turns typed functions into endpoints and documents them at `/docs`.
- **WHERE:** `app/api/routes.py` (`/plan`, `/research`, `/health`, `/health/ready`, `/version`, `/metrics`).
- **EXAMPLE:** `curl localhost:8000/api/v1/health` → `{"status":"ok",...}`. Chapter: [05](05_api.md).

### 3. JSON
- **WHAT:** text format for data: `{"destination": "Goa", "num_days": 4}`.
- **WHY:** every component (browser, API, LLM output, logs) speaks it.
- **HOW:** Pydantic converts JSON ↔ Python objects and validates it.
- **WHERE:** `app/schemas/`. Chapter: [12](12_data_models.md).
- **EXAMPLE:** `num_days: 40` → 422 "less than or equal to 14".

### 4. LLM
- **WHAT:** a model that continues text plausibly.
- **WHY:** reading messy web pages and balancing soft preferences can't be written as rules.
- **HOW:** a prompt goes in, text (here: JSON) comes out; it can be wrong, so we check it.
- **WHERE:** `app/llm/client.py`. Chapter: [06](06_llm_basics.md).
- **EXAMPLE:** "Extract places from these sources" → `{"attractions": [{"name": "Baga Beach", "source_id": "S2"}]}`.

### 5. Gemini
- **WHAT:** Google's LLM (`gemini-2.5-flash`).
- **WHY:** good structured output, free tier, fits GCP.
- **HOW:** called with a JSON schema; temperature 0 for extraction, 0.3 for planning.
- **WHERE:** `app/llm/factory.py`. Chapter: [08](08_gemini.md).
- **EXAMPLE:** missing key → 503 `CONFIGURATION_ERROR` naming `GEMINI_API_KEY`.

### 6. Search API
- **WHAT:** Tavily: web search for programs.
- **WHY:** current facts; the LLM's memory is frozen.
- **HOW:** 5 fixed queries per trip, in parallel; results cleaned and numbered S1..Sn.
- **WHERE:** `app/tools/search/`, `app/research/`. Chapter: [07](07_search_layer.md).
- **EXAMPLE:** "best mid-range hotels in Goa price per night".

### 7. LangChain
- **WHAT:** building blocks for LLM apps.
- **WHY:** one chat-model interface (Gemini, demo model, test fakes), prompt templates, standard errors.
- **HOW:** we use only those core pieces.
- **WHERE:** `app/prompts/`, `app/llm/`.
- **EXAMPLE:** tests swap Gemini for `ScriptedChatModel` without touching app code.

### 8. LangGraph
- **WHAT:** runs a workflow as a graph of steps sharing a state.
- **WHY:** parallel searches, then fixed steps, and one bounded loop (validate ⇄ repair).
- **HOW:** nodes return partial state; edges (including conditional ones) define order.
- **WHERE:** `app/graph/research_graph.py`, `planning_graph.py`. Chapter: [09](09_research_pipeline.md).
- **EXAMPLE:** `validate_itinerary` → `repair_itinerary` if errors and attempts < 2.

### 9. Grounding
- **WHAT:** making the answer rely only on verified evidence.
- **WHY:** stops invented places and prices.
- **HOW:** entity names and price quotes must appear in their cited source; the plan may only use verified ids; free text is checked for unverified names.
- **WHERE:** `app/research/grounding.py`, `app/planning/named_places.py`. Chapter: [10](10_hallucination_control.md).
- **EXAMPLE:** "Dudhsagar Falls" cited to a page that never mentions it → rejected.

### 10. Itinerary generation
- **WHAT:** Gemini arranges verified places into days and time slots.
- **WHY:** judgement about fit and grouping is the LLM's strength.
- **HOW:** it returns ids or generic kinds; code adds titles, dates, areas and prices.
- **WHERE:** `app/prompts/planner_prompt.py`, `app/planning/assembler.py`. Chapter: [13](13_itinerary_planning.md).
- **EXAMPLE:** `{"place_id": "A1"}` → "Visit Baga Beach".

### 11. Validation
- **WHAT:** code checks of the draft.
- **WHY:** LLMs miscount and misremember.
- **HOW:** errors (unknown ids, wrong day count, unverified names) vs warnings (diet unverified, over budget).
- **WHERE:** `app/planning/validator.py`. Chapter: [14](14_validation_and_repair.md).
- **EXAMPLE:** `place_id: "A99"` → `UNKNOWN_PLACE_ID`.

### 12. Repair
- **WHAT:** sending the errors back to Gemini to fix.
- **WHY:** self-correction with feedback is cheaper than failing.
- **HOW:** at most 2 rounds, then 502 `ITINERARY_INVALID`.
- **WHERE:** `planning_graph.repair_itinerary`.
- **EXAMPLE:** demo mode always shows one successful repair.

### 13. Budget
- **WHAT:** cost per category plus total.
- **WHY:** arithmetic must be exact; LLMs aren't.
- **HOW:** verified prices first, labelled defaults otherwise, unknowns flagged.
- **WHERE:** `app/planning/budget.py`. Chapter: [15](15_budget_engine.md).
- **EXAMPLE:** "₹4,000/room/night × 3 nights × 1 room (estimate)".

### 14. Streamlit
- **WHAT:** a Python web UI.
- **WHY:** no JavaScript needed.
- **HOW:** calls the API over HTTP; escapes untrusted text.
- **WHERE:** `frontend/`. Chapter: [16](16_frontend.md).
- **EXAMPLE:** yellow DEMO banner in demo mode.

### 15. Logging
- **WHAT:** one JSON line per important event.
- **WHY:** answer "what happened to request X?".
- **HOW:** `log_event(logger, "llm_call", latency_ms=…)`, all sharing `request_id`.
- **WHERE:** `app/observability/logging.py`. Chapter: [18](18_observability.md).
- **EXAMPLE:** `{"event_type": "search_call", "category": "hotels", "outcome": "error", ...}`.

### 16. Metrics
- **WHAT:** counters and timings.
- **WHY:** trends: "how often does repair happen?".
- **HOW:** in-process registry at `/api/v1/metrics`.
- **WHERE:** `app/observability/metrics.py`.
- **EXAMPLE:** `repair_success_total`, `llm_calls_total{purpose,outcome}`.

### 17. DeepEval
- **WHAT:** a framework for scoring LLM outputs.
- **WHY:** code tests can't measure answer quality.
- **HOW:** 10 fixed trips, 7 code metrics, 4 LLM-judge metrics, JSON report.
- **WHERE:** `evaluation/`. Chapters: [17](17_llm_evaluation_basics.md), [19](19_deepeval.md).
- **EXAMPLE:** `python -m evaluation.runner --mode demo`.

### 18. Docker
- **WHAT:** packages app + dependencies into an image.
- **WHY:** identical everywhere; the unit Kubernetes runs.
- **HOW:** multi-stage, non-root, healthcheck.
- **WHERE:** `Dockerfile`, `frontend/Dockerfile`. Chapter: [21](21_docker.md).
- **EXAMPLE:** `docker build -t ai-travel-planner-api:local .`.

### 19. Docker Compose
- **WHAT:** runs several containers together.
- **WHY:** one command for the local stack.
- **HOW:** services, network, volumes; ELK as an optional profile.
- **WHERE:** `docker-compose.yml`. Chapter: [22](22_docker_compose.md).
- **EXAMPLE:** `docker compose --profile elk up --build`.

### 20. ELK
- **WHAT:** Logstash (pipeline) → Elasticsearch (store) → Kibana (UI).
- **WHY:** searchable logs locally.
- **HOW:** Logstash tails the API's JSON log file.
- **WHERE:** `monitoring/elk/`. Chapter: [20](20_elk_stack.md).
- **EXAMPLE:** KQL `event_type : "llm_call" and not outcome : "ok"`.

### 21. Kubernetes
- **WHAT:** keeps containers running across machines.
- **WHY:** replicas, self-healing, rolling updates, autoscaling.
- **HOW:** Deployments, Services, ConfigMaps, probes, HPA, NetworkPolicy.
- **WHERE:** `infrastructure/kubernetes/`. Chapter: [23](23_kubernetes.md).
- **EXAMPLE:** `kubectl apply -k infrastructure/kubernetes/overlays/local`.

### 22. GCP
- **WHAT:** Google Cloud Platform.
- **WHY:** managed Kubernetes, registry, secrets and logging; Gemini lives there too.
- **HOW:** one project with the needed APIs enabled.
- **WHERE:** [24](24_gcp.md).
- **EXAMPLE:** `gcloud services enable container.googleapis.com ...`.

### 23. GKE
- **WHAT:** Google Kubernetes Engine (Autopilot).
- **WHY:** Google runs the control plane and nodes.
- **HOW:** `gcloud container clusters create-auto`.
- **WHERE:** `overlays/gke/`.
- **EXAMPLE:** the Ingress creates a Google load balancer for the UI.

### 24. Artifact Registry
- **WHAT:** private image storage.
- **WHY:** GKE pulls images from it.
- **HOW:** build, tag with git SHA, push.
- **WHERE:** `deploy.yml`, docs/24 §2.
- **EXAMPLE:** `REGION-docker.pkg.dev/PROJECT_ID/travel-planner/api:3f79eae`.

### 25. Secret Manager
- **WHAT:** encrypted, versioned, audited secret storage.
- **WHY:** keys never in images, YAML or Git; no key files.
- **HOW:** mounted as files through Workload Identity; read via `SECRETS_DIR`.
- **WHERE:** `overlays/gke/secret-provider-class.yaml`, `app/config.py`.
- **EXAMPLE:** `/var/secrets/GEMINI_API_KEY`.

### 26. GitHub Actions
- **WHAT:** automation that runs on GitHub's machines.
- **WHY:** every change tested the same way.
- **HOW:** YAML workflows triggered by PRs, pushes or a button.
- **WHERE:** `.github/workflows/`. Chapter: [26](26_cicd.md).
- **EXAMPLE:** a PR runs ruff, 300 tests, pip-audit, kubeconform.

### 27. CI/CD
- **WHAT:** continuous integration (test every change) + continuous deployment (ship tested commits automatically).
- **WHY:** fast feedback; repeatable, reversible releases.
- **HOW:** CI → (main) images + scans → deploy after CI success, with rollback on failure; live LLM evaluation only on demand.
- **WHERE:** `ci.yml`, `deploy.yml`, `eval-live.yml`.
- **EXAMPLE:** a failed rollout runs `kubectl rollout undo`.

---
**What is verified and what is not:** see the status table in [README.md](../README.md).
