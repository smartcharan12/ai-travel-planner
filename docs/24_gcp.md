# 24 — Google Cloud: GKE, Artifact Registry, Secret Manager, Workload Identity, Cloud Logging (Phases 5.11–5.16, 5.36)

> **Status: DOCUMENTED ONLY. Nothing here has been executed.** No GCP project, credentials or `gcloud` were
> available. Commands use placeholders (`PROJECT_ID`, `PROJECT_NUMBER`, `REGION`, `OWNER/REPO`). Check flags
> against current Google Cloud documentation before running; product flags change. Running this **costs money**
> (load balancer, cluster, logging); create a budget alert first.

## Target architecture

```mermaid
flowchart TB
    DEV[git push to main] --> GH[GitHub Actions<br/>CI: tests, build, scan]
    GH -- OIDC token, no key --> WIF[Workload Identity Federation]
    WIF --> AR[(Artifact Registry<br/>travel-planner/api, /frontend)]
    GH -- kubectl apply -k overlays/gke --> GKE
    subgraph GKE[GKE Autopilot cluster]
      LB[Ingress → Google Cloud HTTP(S) LB] --> UI[frontend pod]
      UI --> API1[api pod] & API2[api pod]
      CSI[Secret Manager add-on<br/>CSI volume /var/secrets] -.files.-> API1
    end
    SM[(Secret Manager<br/>gemini-api-key, tavily-api-key)] -. Workload Identity .-> CSI
    API1 -- HTTPS --> G[(Gemini API)] & T[(Tavily API)]
    API1 & UI -- stdout JSON --> CL[Cloud Logging] --> CM[Cloud Monitoring<br/>log-based metrics, alerts]
    USER[Browser] --> LB
```

**LOCAL vs GCP observability (deliberate):**

| | Local (docker-compose) | GCP (GKE) |
|---|---|---|
| Collection | Logstash tails a log file | GKE's logging agent reads container **stdout** automatically |
| Storage and search | Elasticsearch + Kibana | Cloud Logging (Logs Explorer) |
| Metrics and alerts | `/api/v1/metrics`, Kibana | Cloud Monitoring (log-based metrics, alerting) |
| Who operates it | you | Google |

Running ELK on GKE would mean operating a stateful search cluster (storage, upgrades, security) to duplicate
what Cloud Logging already provides. ELK stays the **local and self-managed** option. The app needs no change:
it always writes JSON to stdout, and `LOG_FILE` is simply not set on GKE.

## Services used and why

| Service | Why |
|---|---|
| **GKE Autopilot** | managed Kubernetes. Google runs the control plane **and** the nodes (node pools, scaling, upgrades); you pay per pod resource request. Workload Identity and Dataplane V2 (NetworkPolicy enforcement) come built in. Simplest correct choice for a small service. |
| **Artifact Registry** | private Docker registry next to the cluster; GKE pulls from it |
| **Secret Manager** | stores API keys encrypted, versioned and access-audited, outside Kubernetes |
| **Workload Identity** | pods and CI get short-lived Google credentials **without JSON key files** |
| **Cloud Load Balancing** | created by the Ingress; HTTPS termination, optional Cloud Armor |
| **Cloud Logging / Monitoring** | collects stdout, search, log-based metrics, alerts |

(GKE Standard is the alternative: you manage node pools, e.g. `gcloud container node-pools create`. More control,
more work; not needed here.)

## 1. Project, billing, APIs
```bash
gcloud auth login
gcloud config set project PROJECT_ID                 # a project with BILLING ENABLED (required)
gcloud config set compute/region REGION              # e.g. asia-south1 (Mumbai)
gcloud services enable container.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com
PROJECT_NUMBER=$(gcloud projects describe PROJECT_ID --format='value(projectNumber)')
```

## 2. Artifact Registry
**Concepts:** an **image** is the packaged app; a **registry** stores images (`REGION-docker.pkg.dev`); a
**repository** is a named collection in it (`travel-planner`); a **tag** is a movable label (`:3f79eae`,
`:latest`); a **digest** is the immutable content hash (`@sha256:…`). Deploying by git-SHA tag gives traceability;
pinning by digest guarantees the exact bytes.
```bash
gcloud artifacts repositories create travel-planner --repository-format=docker --location=REGION
gcloud auth configure-docker REGION-docker.pkg.dev
TAG=$(git rev-parse --short HEAD)
docker build -t REGION-docker.pkg.dev/PROJECT_ID/travel-planner/api:$TAG --build-arg GIT_SHA=$TAG .
docker build -t REGION-docker.pkg.dev/PROJECT_ID/travel-planner/frontend:$TAG -f frontend/Dockerfile .
docker push REGION-docker.pkg.dev/PROJECT_ID/travel-planner/api:$TAG
docker push REGION-docker.pkg.dev/PROJECT_ID/travel-planner/frontend:$TAG
```
GKE pulls these with the node's service account. If pulls fail with 403 / `ImagePullBackOff`, grant
`roles/artifactregistry.reader` on the repository to the node service account.

## 3. GKE cluster
```bash
gcloud container clusters create-auto travel-planner --location=REGION --enable-secret-manager
gcloud container clusters get-credentials travel-planner --location=REGION
kubectl get nodes
```
`--enable-secret-manager` turns on the Secret Manager add-on (CSI driver `secrets-store-gke.csi.k8s.io`) used by
`overlays/gke/secret-provider-class.yaml`. Networking: Autopilot clusters are VPC-native; the Ingress uses
container-native load balancing (NEGs, the `cloud.google.com/neg` annotation).

## 4. Secrets: local vs Kubernetes vs Secret Manager (not equivalent)

| Where | Mechanism | Protection | Use for |
|---|---|---|---|
| Laptop | `.env` (git-ignored) | file permissions only | development |
| Any cluster | Kubernetes Secret | base64 in etcd (not encryption); RBAC; GKE encrypts etcd at rest | local clusters, quick tests |
| GKE production | **Secret Manager** + CSI mount | encrypted, versioned, IAM per secret, audit logs, rotation without rebuilding | **recommended** |

```bash
printf '%s' "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- --replication-policy=automatic
printf '%s' "$TAVILY_API_KEY" | gcloud secrets create tavily-api-key --data-file=- --replication-policy=automatic
# allow ONLY the api pods' Kubernetes ServiceAccount (travel-planner/api) to read them:
for s in gemini-api-key tavily-api-key; do
  gcloud secrets add-iam-policy-binding $s --role=roles/secretmanager.secretAccessor \
    --member="principal://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/PROJECT_ID.svc.id.goog/subject/ns/travel-planner/sa/api"
done
```
The add-on mounts them as `/var/secrets/GEMINI_API_KEY` and `/var/secrets/TAVILY_API_KEY`; the app reads them via
`SECRETS_DIR=/var/secrets` (pydantic-settings `secrets_dir`, tested in `tests/unit/test_production_hardening.py`).
Rotation: add a new secret version, then `kubectl rollout restart deploy/api`.

## 5. Workload Identity (no JSON keys)
**Why JSON service-account keys are dangerous:** they are long-lived bearer credentials. Anyone who gets the file
(a leaked image layer, a log, a laptop, a CI secret) acts as that identity until someone notices and revokes
it. They're the most common GCP credential leak.

**Workload Identity:** Google trusts a short-lived identity token that the platform issues automatically. Pods
(Workload Identity Federation for GKE: the binding above names the Kubernetes ServiceAccount directly) and GitHub
Actions (Workload Identity Federation with GitHub's OIDC tokens) get credentials that expire within an hour, and
nothing is stored to steal.

**GitHub → GCP (for `deploy.yml`):**
```bash
gcloud iam workload-identity-pools create github --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github --location=global --workload-identity-pool=github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='OWNER/REPO'"
gcloud iam service-accounts create gh-deployer --display-name="GitHub deployer"
gcloud projects add-iam-policy-binding PROJECT_ID --role=roles/container.developer \
  --member=serviceAccount:gh-deployer@PROJECT_ID.iam.gserviceaccount.com
gcloud artifacts repositories add-iam-policy-binding travel-planner --location=REGION \
  --role=roles/artifactregistry.writer --member=serviceAccount:gh-deployer@PROJECT_ID.iam.gserviceaccount.com
gcloud iam service-accounts add-iam-policy-binding gh-deployer@PROJECT_ID.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/OWNER/REPO"
```
Then set the GitHub repository **variables**: `GCP_PROJECT_ID`, `GCP_REGION`, `GKE_CLUSTER=travel-planner`,
`GCP_WIF_PROVIDER=projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github`,
`GCP_DEPLOY_SA=gh-deployer@PROJECT_ID.iam.gserviceaccount.com`. No GitHub *secret* is needed.

## 6. Deploy
```bash
gcloud compute addresses create travel-planner-ip --global          # referenced by ingress.yaml
cd infrastructure/kubernetes/overlays/gke
sed -i "s/REGION/<region>/g; s/PROJECT_ID/<project>/g; s/REPLACE_WITH_GIT_SHA/$TAG/g" kustomization.yaml secret-provider-class.yaml
kubectl apply -k .
kubectl -n travel-planner rollout status deploy/api
kubectl -n travel-planner get ingress frontend          # EXTERNAL IP after a few minutes
```
(The deploy workflow does exactly this, without committing the substituted values.) HTTPS: point a domain at the
static IP, edit `managed-certificate.yaml`, enable it in `kustomization.yaml` and the Ingress annotation.

## 7. Cloud Logging and Monitoring
```text
app → stdout (JSON lines) → GKE logging agent → Cloud Logging (jsonPayload.*) → Cloud Monitoring (log-based metrics, alerts)
```
**Why stdout in containers:** containers are disposable; files inside them vanish with the pod and need extra
agents to collect. The platform already captures stdout/stderr for every container. Our JSON lines carry
`severity` (which Cloud Logging uses for the log level), `message`, `request_id` and all event fields.

Useful Logs Explorer queries:
```text
resource.type="k8s_container" resource.labels.namespace_name="travel-planner" jsonPayload.event_type="llm_call" jsonPayload.outcome!="ok"
jsonPayload.request_id="<X-Request-ID>"
severity>=ERROR
```
Log-based metric and alert example:
```bash
gcloud logging metrics create llm_call_failures \
  --description="LLM calls not ok" \
  --log-filter='resource.labels.namespace_name="travel-planner" AND jsonPayload.event_type="llm_call" AND jsonPayload.outcome!="ok"'
# then create an alerting policy on logging.googleapis.com/user/llm_call_failures in Cloud Monitoring
```

## 8. Cost and teardown
Main cost drivers: Autopilot pod requests (2 API + 1 UI ≈ 0.5 vCPU, ~0.7 GiB), the external load balancer (fixed
hourly), logging ingestion above the free allotment, and **Gemini/Tavily usage** (likely the largest at any real
traffic). Tear down:
```bash
kubectl delete -k infrastructure/kubernetes/overlays/gke
gcloud container clusters delete travel-planner --location=REGION
gcloud compute addresses delete travel-planner-ip --global
gcloud artifacts repositories delete travel-planner --location=REGION
```

## Future option
Use Gemini through **Vertex AI** with Workload Identity instead of an API key; then there is no Gemini secret at
all. That needs a small change to the LLM factory (`ChatGoogleGenerativeAI` supports Vertex AI); not done.
