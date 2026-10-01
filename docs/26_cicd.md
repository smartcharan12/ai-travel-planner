# 26 — CI/CD with GitHub Actions (Phases 5.17–5.19)

Files: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`deploy.yml`](../.github/workflows/deploy.yml),
[`eval-live.yml`](../.github/workflows/eval-live.yml).

> **Status: NOT RUN on GitHub** (the repository has no remote yet). **VERIFIED locally:** `actionlint` reports no
> problems; every action input was checked against the action's `action.yml` at the pinned version;
> `tests/unit/test_workflows.py` enforces the security rules below. Each command the CI runs was also run
> locally (ruff, pytest, demo evaluation, pip-audit, kustomize + kubeconform, hadolint); Docker steps were not.

## Concepts
- **CI (continuous integration):** every change is automatically linted and tested, so a broken `main` is caught
  in minutes, not days.
- **CD (continuous delivery/deployment):** after CI passes, the exact tested commit is packaged and deployed by
  a script, not by hand.
- **Workflow / job / step:** a YAML file / a VM run / one command or action within it.
- **Runner:** the GitHub-hosted VM (`ubuntu-latest`).

## Pipeline

```mermaid
flowchart LR
    PR[pull request] --> T[test: ruff, unit/API/frontend, integration, demo eval]
    PR --> DA[dependency-audit: pip-audit]
    PR --> M[manifests: kustomize + kubeconform]
    MAIN[push to main] --> T & DA & M
    T --> I[images: hadolint, compose config, build API+UI,<br/>container smoke test, Trivy scan]
    I -. CI succeeded on main .-> D[deploy.yml: WIF auth → build+push to Artifact Registry →<br/>kubectl apply -k overlays/gke → rollout status → undo on failure]
    MAN[manual button] --> L[eval-live.yml: live tests + live DeepEval (+judge)]
```

## Test strategy: why these layers

| Trigger | Runs | Why |
|---|---|---|
| Pull request | lint, all offline tests, demo evaluation, pip-audit, manifest validation | fast (minutes), free, no secrets; catches nearly all code mistakes |
| Push to `main` | the above + Docker builds, container smoke test, Trivy | slower; image-level problems matter once code is merging |
| CI success on `main` | deploy (only when GCP variables are configured; approval via the `production` environment) | deploys exactly what was tested |
| Manual | live smoke tests + live DeepEval, optional LLM judge | costs API credits and varies with the web, so running it on every commit would be expensive noise |

The demo evaluation in CI uses `--report-only`: the demo data is *expected* to fail `preference_match` on two
cases (docs/19). The report is uploaded as an artifact. Failing CI on it would just teach people to ignore red builds.

## Step by step (`ci.yml`)
1. `actions/checkout@v7`: get the code.
2. `actions/setup-python@v7`: Python 3.12 with pip caching keyed on the requirements files.
3. `pip install -r requirements-eval.txt`: app + frontend + test tools + DeepEval.
4. `ruff check .` and `ruff format --check .`: lint and formatting.
5. `pytest tests/unit tests/api tests/frontend`, then `pytest tests/integration`: separate steps so failures are easy to locate.
6. Demo evaluation: DeepEval research suite + runner report (artifact).
7. `pip-audit` on the runtime requirements of both images.
8. `kubectl kustomize` both overlays → `kubeconform -strict` (with CRD schemas).
9. (main) hadolint, `docker compose config`, build both images with Buildx (layer cache in GitHub's cache).
10. (main) Smoke test: run the API image in demo mode; check health, readiness, a real `/plan` request, uid 10001,
    and that no `.env` exists in the image.
11. (main) Trivy scans both images; fails on fixable CRITICAL/HIGH vulnerabilities.

## Secrets and identity

| Workflow | Needs | Where |
|---|---|---|
| `ci.yml` | nothing | `permissions: contents: read`; a test asserts it references no secrets |
| `deploy.yml` | GCP access | **Recommended:** Workload Identity Federation: repository *variables* `GCP_PROJECT_ID`, `GCP_REGION`, `GKE_CLUSTER`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`; `permissions: id-token: write`; no stored credential. **Simple alternative (not recommended):** a service-account JSON key in secret `GCP_SA_KEY` with `credentials_json:` (commented out in the file). It's long-lived and leakable; see docs/24 §5 |
| `eval-live.yml` | `GEMINI_API_KEY`, `TAVILY_API_KEY` | GitHub **secrets**, scoped to an `evaluation` environment |

Never write a secret value into a workflow. GitHub masks secrets in logs, but only if they come from `secrets.*`.

## Deployment safety
- Runs only after CI succeeded for that commit (`workflow_run` + `conclusion == 'success'`), or manually.
- Images are tagged with the git SHA: what's running is traceable to a commit.
- `environment: production`: add required reviewers for a manual approval gate.
- `kubectl rollout status` waits for readiness probes; on failure, `rollout undo` restores the previous ReplicaSet.
- `concurrency: deploy-production` prevents two deploys racing.
- Without the repository variables, the job is skipped, so forks never try to deploy.

## First run checklist (when the repo is on GitHub)
1. Push and open a PR → `test`, `dependency-audit`, `manifests` should pass.
2. Merge → `images` runs (first real Docker build and Trivy result; fix findings if any).
3. Follow docs/24, set the variables → deploy runs.
4. Add Gemini/Tavily secrets → run "Live LLM evaluation" manually.
