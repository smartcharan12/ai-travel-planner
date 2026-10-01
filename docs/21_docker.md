# 21 — Docker (Phases 4.22, 4.24, 4.25)

Files: [`Dockerfile`](../Dockerfile) (API), [`frontend/Dockerfile`](../frontend/Dockerfile) (UI), [`.dockerignore`](../.dockerignore).

> **Status: written and statically tested, NOT BUILT.** Docker is not installed on the build machine.
> `tests/unit/test_container_config.py` checks the security properties below, but `docker build` has
> never been run by the author.

## Concepts
| Term | Meaning | Here |
|---|---|---|
| **image** | a read-only package: OS files + Python + dependencies + our code | `ai-travel-planner-api:local` |
| **container** | a running instance of an image, isolated from other processes | the API process |
| **Dockerfile** | the recipe for an image | `Dockerfile` |
| **layer** | each instruction adds a cached layer; unchanged layers are reused | dependencies cached separately from code |
| **port** | a container port published to the host | 8000 (API), 8501 (UI) |
| **volume** | storage that outlives a container | `app-logs` (JSON logs for Logstash) |
| **environment variable** | runtime configuration | `GEMINI_API_KEY`, `DEMO_MODE`, `LOG_FILE` |
| **network** | containers talking by service name | the UI calls `http://api:8000` |

## The API Dockerfile, instruction by instruction

| Instruction | Why |
|---|---|
| `ARG PYTHON_IMAGE=python:3.12.14-slim-trixie` | pinned, small (Debian slim) base; one place to change it |
| `FROM … AS builder` | **stage 1** builds dependencies; pip and its caches never reach the final image |
| `ENV PIP_NO_CACHE_DIR=1 …` | no pip cache stored in layers |
| `RUN python -m venv /opt/venv` + `ENV PATH=…` | a self-contained virtualenv that can be copied whole |
| `COPY requirements.txt .` then `RUN pip install …` | dependency layer cached until requirements change, so code edits rebuild in seconds |
| `FROM … AS runtime` | **stage 2**: a clean image with only what runs |
| `ARG GIT_SHA` → `ENV GIT_SHA` | `/api/v1/version` shows the exact commit (set by CI, docs/26) |
| `ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1` | no `.pyc` files; logs flushed immediately |
| `ENV LOG_FORMAT=json` | containers log JSON by default |
| `RUN groupadd … useradd … uid 10001` + `mkdir /var/log/app && chown` | an **unprivileged user**, owning only the log directory |
| `COPY --from=builder /opt/venv /opt/venv` | dependencies from stage 1 |
| `COPY app ./app` | **only** the application package: no tests, docs, evaluation, `.env` |
| `USER app` | the process does not run as root |
| `EXPOSE 8000` | documents the port |
| `HEALTHCHECK … /api/v1/health` | Docker marks the container healthy/unhealthy; uses Python's `urllib` (no curl needed in slim) |
| `CMD ["uvicorn", …, "--no-access-log"]` | exec form: uvicorn is PID 1 and receives SIGTERM for graceful shutdown; access log off because the middleware writes richer `request_completed` events; 1 worker per container, scaled by adding containers |

The frontend Dockerfile follows the same pattern with `frontend/requirements.txt` (Streamlit + httpx only),
a user *with* a home directory (Streamlit writes small files there), `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`,
and a healthcheck on `/_stcore/health`.

## Security checklist (Phase 4.24)

| Requirement | How | Checked by |
|---|---|---|
| no `.env` in the image | `.dockerignore` excludes `.env`, `.env.*`; Dockerfiles only `COPY` requirements + code | test |
| no keys in Dockerfile | none; keys come from `--env-file` / compose `env_file` / Kubernetes Secret at run time | test (regex) |
| non-root | `USER app` (uid 10001) | test |
| minimal dependencies | API image installs `requirements.txt` only: no Streamlit, DeepEval, pytest | test |
| no unnecessary ports | API exposes 8000 only; compose binds to 127.0.0.1 | test |
| pinned images | no `:latest` anywhere | test |
| small attack surface | slim base, multi-stage, no compilers in the runtime stage | review |

## Health checks (Phase 4.25)

| Endpoint | Question | Checks | Used by |
|---|---|---|---|
| `/api/v1/health` (liveness) | "Is the process alive?" | nothing external | Dockerfile `HEALTHCHECK`, compose `service_healthy`, Kubernetes liveness probe (docs/23) |
| `/api/v1/health/ready` (readiness) | "Should it receive traffic?" | required keys present for the configured providers | Kubernetes readiness probe (docs/23) |

Neither calls Gemini or Tavily: a health check runs every few seconds, and calling a paid API that often
would cost money, hit rate limits, and make our health depend on theirs. (If Gemini is down, restarting our
container doesn't help.)

## Build and run without compose
```bash
docker build -t ai-travel-planner-api:local --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env ai-travel-planner-api:local
docker build -f frontend/Dockerfile -t ai-travel-planner-frontend:local .
```
