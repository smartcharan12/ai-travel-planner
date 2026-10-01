# syntax=docker/dockerfile:1
# API image for the AI Travel Planner (FastAPI + LangGraph).
# Every instruction is explained in docs/21_docker.md.
#
#   docker build -t ai-travel-planner-api:local --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
#   docker run --rm -p 8000:8000 --env-file .env ai-travel-planner-api:local
#
# Secrets are NEVER part of the image: pass them at run time (--env-file, compose env_file,
# Kubernetes Secret). .dockerignore keeps .env out of the build context entirely.

ARG PYTHON_IMAGE=python:3.12.14-slim-trixie

# ---------- stage 1: build the virtualenv (has pip and build caches; thrown away) ----------
FROM ${PYTHON_IMAGE} AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# Copy only the dependency list first: this layer is cached until requirements.txt changes,
# so editing application code does not reinstall every package.
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------- stage 2: the runtime image (only what is needed to run) ----------
FROM ${PYTHON_IMAGE} AS runtime
ARG GIT_SHA=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    GIT_SHA=${GIT_SHA} \
    LOG_FORMAT=json

# Unprivileged user: if the app is compromised, the attacker is not root in the container.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/log/app \
    && chown app:app /var/log/app

WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
# Code is owned by root and read-only for the app user.
COPY app ./app

# Numeric UID:GID so Kubernetes `runAsNonRoot` can verify the user is not root.
USER 10001:10001
EXPOSE 8000

# Liveness only (cheap, no external calls). Readiness (/api/v1/health/ready) is for orchestrators.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"]

# Exec form: uvicorn is PID 1 and receives SIGTERM directly for a graceful shutdown.
# --timeout-graceful-shutdown: on SIGTERM, stop accepting new requests and give in-flight plans
# (LLM calls take tens of seconds) up to 60 s to finish. Kubernetes allows 75 s before SIGKILL.
# One worker per container: scale by running more containers (metrics are per process).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log", "--timeout-graceful-shutdown", "60"]
