# 25 — Security review (Phases 5.9, 5.20–5.25)

A review of each area: what protects it, how it was checked, and what remains. Labels: **VERIFIED** (tested
here), **DOCUMENTED ONLY** (configured or written, not executed), **GAP** (known, not addressed).

| Area | Controls | Status |
|---|---|---|
| **Input validation** | Pydantic schemas with `extra="forbid"`; place names letters/punctuation only and single line; length caps; enums for preferences; date rules | VERIFIED (tests/unit/test_request_schema.py) |
| **Prompt injection (user)** | free text only in `special_requirements`: single-line, ≤ 300 chars, never sent to search or extraction; in the planner prompt it sits inside `<traveller_notes>` with `<`/`>` neutralised and a rule that it can't change instructions | VERIFIED (prompt tests) |
| **Prompt injection (web pages)** | source text only inside `<source>` blocks; tag look-alikes stripped; system prompt says sources are untrusted data; **grounding** rejects entities whose names don't appear in their cited source; planner can only use verified ids; the named-place check rejects unverified names in LLM text | VERIFIED (normalizer, grounding, named-place tests). GAP: a malicious page can still promote a place it genuinely mentions |
| **Output safety** | UI escapes Markdown (`md_escape`); Streamlit escapes HTML; URLs http(s) only (schema) and shown via link columns | VERIFIED (frontend tests) |
| **API key protection** | `SecretStr`; keys only from env, `.env` (git-ignored) or Secret Manager files; never in images, compose YAML, ConfigMaps or workflows; readiness reports variable *names* only | VERIFIED (config, container, k8s, workflow tests); gitleaks: 0 findings in project files |
| **Error leakage** | one error format; unexpected errors → generic 500; provider messages and stack traces only in server logs | VERIFIED (test_unexpected_errors_do_not_leak_details, LLM/search error tests) |
| **Logging** | secret-looking fields dropped by the formatter and again by Logstash; prompts and free text never logged; request ids validated before echoing | VERIFIED (observability tests) |
| **CORS** | off by default (the UI calls the API server-side); explicit origins via `CORS_ALLOW_ORIGINS`; `*` refused when `APP_ENV=prod`; only GET/POST and two headers; no credentials | VERIFIED (test_production_hardening.py) |
| **Rate limiting / abuse** | per-client 20/min and per-replica max 8 concurrent plans on `/plan` and `/research`; `Retry-After` header; metric `rate_limited_total` | VERIFIED. GAP: per-process, so the effective limit multiplies with replicas, and with the UI as caller all users share one key. Real per-user limits belong at the edge (below) |
| **Request ids** | client-supplied ids accepted only if `[A-Za-z0-9-]{8,64}`, which blocks log injection | VERIFIED |
| **Dependencies** | exact pins; `pip-audit` on both images' requirements: **"No known vulnerabilities found"** (2026-10-02); runs in CI | VERIFIED locally; CI DOCUMENTED ONLY (no run yet) |
| **Containers** | multi-stage slim images; numeric non-root user 10001; no secrets; healthchecks; hadolint clean; Trivy scan in CI (CRITICAL/HIGH, fixed-only) | hadolint VERIFIED; build and Trivy **NOT RUN** (no Docker) |
| **Kubernetes** | runAsNonRoot, read-only root FS, drop ALL capabilities, no privilege escalation, seccomp, no SA token, resource limits, default-deny NetworkPolicy, API not exposed, metadata server blocked | manifests VERIFIED statically (kubeconform + tests); cluster behaviour NOT RUN |
| **Cloud identity** | Workload Identity for pods and CI; no JSON keys; per-secret IAM | DOCUMENTED ONLY |
| **Supply chain** | Actions pinned to major versions; CI token read-only; deploy only gets `id-token: write` | DOCUMENTED. GAP: pin actions to commit SHAs; sign images (cosign) |
| **Authentication** | none: the API is internal (ClusterIP + NetworkPolicy), the UI is public and anonymous | GAP: add login (e.g. Identity-Aware Proxy in front of the Ingress) before real users |

## Edge protection (recommended for production, DOCUMENTED ONLY)
Cloud Armor security policy on the load balancer:
```bash
gcloud compute security-policies create travel-planner-armor
gcloud compute security-policies rules create 1000 --security-policy=travel-planner-armor \
  --expression="true" --action=throttle --rate-limit-threshold-count=60 \
  --rate-limit-threshold-interval-sec=60 --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP
```
Then uncomment `securityPolicy` in `overlays/gke/backend-config.yaml`. The edge sees real client IPs, which the
in-app limiter cannot.

## Image and dependency scanning, explained
- **Vulnerability (CVE):** a publicly known flaw in a specific package version.
- **Base image:** OS packages from `python:3.12.14-slim-trixie`. Slim reduces how many there are; rebuilding
  regularly picks up patched versions.
- **Dependency vulnerabilities:** Python packages. `pip-audit` checks pinned requirements against the PyPA/OSV
  advisory databases.
- **Image scanning (Trivy):** scans the *built* image (OS + Python packages) and fails CI on fixable CRITICAL/HIGH
  issues. `ignore-unfixed` avoids blocking on issues no one can fix yet; review them periodically rather than
  ignoring them forever.
- If a scanner reports a non-actionable issue, add a time-boxed, commented ignore entry instead of disabling the scan.

## Commands actually run
```text
gitleaks dir .               -> 2 findings, both inside .venv (third-party test fixtures); 0 in project files
hadolint Dockerfile, frontend/Dockerfile -> initially DL3045 + DL3066 (fixed: WORKDIR in builder, numeric USER); now clean
pip-audit -r requirements.txt -r frontend/requirements.txt -> No known vulnerabilities found
kubeconform -strict (both overlays) -> 31/31 valid
actionlint                   -> no problems (shellcheck integration not available locally)
```
