# Resume entry (truthful version)

## Title
**AI Travel Planner: grounded LLM itinerary service with an LLMOps toolchain** (personal project)

## Tech stack
Python 3.12 · FastAPI · Pydantic · LangChain (core) · LangGraph · Gemini 2.5 Flash · Tavily search API ·
Streamlit · DeepEval · pytest · Ruff · Docker · Docker Compose · Elasticsearch/Logstash/Kibana · Kubernetes
(Kustomize) · Google Cloud (GKE Autopilot, Artifact Registry, Secret Manager, Workload Identity, Cloud Logging) ·
GitHub Actions · Trivy · pip-audit

## Bullets (pick 3–4)
- Built a FastAPI + LangGraph service that researches destinations with live web search and uses Gemini to plan
  multi-day itineraries **only from places verified against their cited sources**; code-generated titles, a
  place-name grounding check and a bounded validate-and-repair loop prevent unverified venues and invalid plans.
- Kept every number deterministic: a Python budget engine prices plans from verified source quotes or labelled
  estimates, and flags unknown costs instead of letting the LLM guess; validated with **300 automated tests**
  (unit, API, integration, frontend, infrastructure configuration).
- Added LLMOps tooling: a 10-case DeepEval suite with 7 deterministic metrics and 4 LLM-as-judge metrics, plus
  structured JSON logging and metrics for every LLM call, search, validation and repair (request-id correlation,
  token and cost fields).
- Packaged for production: hardened multi-stage Docker images, Docker Compose with ELK, Kubernetes manifests
  (probes, HPA, NetworkPolicy, read-only non-root pods), a GKE deployment design with Secret Manager and Workload
  Identity, and GitHub Actions CI/CD with image scanning and gated deploys.

## Keywords
- **Architecture:** stateless REST API, workflow orchestration, typed contracts, provider abstraction, graceful degradation, bounded retries
- **LLMOps:** structured output, grounding, hallucination control, LLM evaluation, LLM-as-judge, prompt versioning, token/cost observability
- **Deployment:** Docker multi-stage builds, Kubernetes, Kustomize overlays, HPA, PodDisruptionBudget, GKE Autopilot, Artifact Registry, Workload Identity Federation, CI/CD
- **Observability:** structured JSON logs, correlation ids, metrics, ELK, Cloud Logging, log-based metrics

## Metrics: what can and cannot be claimed

| Metric | Value | Status |
|---|---|---|
| Automated tests | 300 passing, 3 live tests skipped | measured |
| Kubernetes manifests | 31/31 valid (kubeconform strict) | measured |
| Demo evaluation | 8/10 cases pass all metrics (invented data) | measured, **demo only**, not a quality claim |
| Pipeline overhead excluding LLM/search | ~30 ms per plan (local, demo) | measured, local only |
| Real end-to-end latency | — | **To be measured** |
| Real itinerary quality (judge / human) | — | **To be measured** |
| LLM cost per plan | — | **To be measured** |
| Production deployment, users, traffic | — | **Not deployed**: do not claim |

Do not write "deployed on GKE", "reduced hallucinations by X%" or "serves N users" unless you have actually done
and measured it.

## If asked "is it deployed?"
"It's deployment-ready but not deployed: the images, manifests, GKE guide and CI/CD are written and statically
validated, and the core pipeline is tested end to end with faked providers and a demo mode. I haven't run it
against the real APIs or on a cluster yet, and I report it that way."
