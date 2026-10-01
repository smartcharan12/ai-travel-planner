# Troubleshooting

Each entry: **Problem · Why · Diagnose · Fix**. Run commands from the repository root.

### `ModuleNotFoundError: No module named 'app'` (or `frontend`, `evaluation`)
- **Why:** command run from another directory, or the virtualenv isn't used.
- **Diagnose:** `pwd`; `which python`.
- **Fix:** `cd ai-travel-planner`; use `.venv/bin/python …` or `source .venv/bin/activate`; `pip install -r requirements-dev.txt`.

### 503 `CONFIGURATION_ERROR` with `details.missing`
- **Why:** real providers selected, keys absent. The app never silently switches to demo data.
- **Diagnose:** `curl localhost:8000/api/v1/health/ready` lists the missing variable *names*.
- **Fix:** add `GEMINI_API_KEY` / `TAVILY_API_KEY` to `.env`, or set `DEMO_MODE=true`; restart (settings are cached).

### Invalid API key: 502 `LLM_AUTH_ERROR` or `SEARCH_PROVIDER_AUTH_ERROR`
- **Why:** the provider rejected the key (typo, revoked, wrong project).
- **Diagnose:** JSON logs: `llm_call` with `outcome: auth_error`, or `search_call` with `error_code`.
- **Fix:** create a new key (aistudio.google.com/apikey, app.tavily.com); never paste keys into code or chat.

### 429 `RATE_LIMITED`
- **Why:** (a) our limiter: `details.reason` = `rate` (per-client/min) or `busy` (concurrency cap); (b) upstream Gemini/Tavily quota (`details.upstream: true`).
- **Diagnose:** response `details`; `Retry-After` header; metric `rate_limited_total`.
- **Fix:** wait; raise `RATE_LIMIT_PER_MINUTE` / `MAX_CONCURRENT_PLANS` for local testing; check provider quotas.

### 502 `LLM_INVALID_OUTPUT` / `ITINERARY_INVALID`
- **Why:** the model returned non-JSON twice, or the plan still broke rules after 2 repairs.
- **Diagnose:** `llm_call` events with `invalid_output`; `itinerary_validated` events list `error_codes` (e.g. `UNSUPPORTED_NAMED_PLACE`).
- **Fix:** retry; if one code dominates, improve the prompt or rule (see `validation_failures_total{code}`).

### JSON parsing errors
- **Why:** malformed request body, or a wrong `Content-Type`.
- **Fix:** send `-H 'Content-Type: application/json'` with valid JSON; the 422 body lists field errors.

### Search API errors: 504 `SEARCH_TIMEOUT`, 502 `SEARCH_PROVIDER_ERROR`, 422 `NO_RESEARCH_RESULTS`
- **Why:** provider slow or down, or nothing usable found for the destination.
- **Diagnose:** `search_call` events per category; `search_summary` in `/research` responses.
- **Fix:** retry; raise `SEARCH_TIMEOUT_SECONDS`; check the destination spelling; try `SEARCH_PROVIDER=serper`.

### Connection refused (UI shows `API_UNREACHABLE`)
- **Why:** API not running, or wrong `API_BASE_URL`.
- **Fix:** start uvicorn; locally `API_BASE_URL=http://localhost:8000`; in compose `http://api:8000`; in Kubernetes the Service DNS name.

### App refuses to start: `ValidationError` in Settings
- **Why:** invalid value (e.g. `LLM_TEMPERATURE=3`), or a production guard (`APP_ENV=prod` with `DEMO_MODE`, `CORS_ALLOW_ORIGINS=*`, or `LOG_FORMAT=text`).
- **Fix:** read the message; it names the variable.

### Docker daemon unavailable (`Cannot connect to the Docker daemon`)
- **Fix:** start Docker Desktop / `sudo systemctl start docker`; Linux: add your user to the `docker` group and re-login.

### Elasticsearch unavailable / exits with code 137
- **Why:** out of memory (needs ~1 GB; the whole ELK profile ~3 GB).
- **Diagnose:** `docker compose logs elasticsearch`; `docker stats`.
- **Fix:** free RAM; lower `ES_JAVA_OPTS`; run without `--profile elk`.

### Kibana unavailable ("Kibana server is not ready yet")
- **Why:** normal for 1–2 minutes after start; or ES unhealthy.
- **Fix:** wait; `docker compose ps`; `docker compose logs elk-setup`.

### No logs in Kibana (`_count` = 0)
- **Fix:** the api service must have `LOG_FILE` (set in compose) and have served a request; check `docker compose logs logstash`.

### Kubernetes: pod `CrashLoopBackOff`
- **Why:** the process exits on start (bad config → Settings error; read-only filesystem write).
- **Diagnose:** `kubectl -n travel-planner logs <pod> --previous`; `kubectl describe pod <pod>`.
- **Fix:** correct the ConfigMap/Secret; `kubectl rollout restart deploy/api`.

### Kubernetes: pod Running but not Ready
- **Why:** readiness `/api/v1/health/ready` returns 503: keys missing.
- **Diagnose:** `kubectl -n travel-planner describe pod -l app=api` (probe events); `kubectl exec … -- python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/v1/health/ready').read())"`.
- **Fix:** create `api-secrets` (local) or check the Secret Manager mount and IAM (GKE).

### Kubernetes: `ImagePullBackOff` / `ErrImagePull`
- **Why:** image not in the cluster (kind: forgot `kind load docker-image`); wrong name/tag; GKE node lacks `artifactregistry.reader`.
- **Diagnose:** `kubectl describe pod` → Events.
- **Fix:** load or push the image; correct the overlay `images:`; grant the reader role.

### GKE: Secret Manager volume fails to mount
- **Why:** add-on not enabled, wrong secret name, or missing IAM binding for `ns/travel-planner/sa/api`.
- **Diagnose:** `kubectl describe pod` → `FailedMount` events.
- **Fix:** docs/24 §3–4.

### GCP authentication errors (`PERMISSION_DENIED`, `Reauthentication required`)
- **Fix:** `gcloud auth login`; `gcloud config set project PROJECT_ID`; check IAM roles (docs/24). In CI: verify the WIF provider's `attribute-condition` matches `OWNER/REPO`.

### Evaluation: `--mode live needs GEMINI_API_KEY…`
- **Why:** by design, live evaluation never falls back to demo.
- **Fix:** add keys, or use `--mode demo` (and read its notice: demo scores say nothing about model quality).
