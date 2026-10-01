"""Static checks that keep the Kubernetes manifests consistent with the code and secure.

They don't replace a real cluster (see the Stage 5 report: NOT RUN), but they catch the
mistakes that are easiest to make: a probe pointing at a route that doesn't exist, a ConfigMap
key the app ignores, a secret in a ConfigMap, a public API, a root container.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "infrastructure" / "kubernetes"


def _docs(path: Path) -> list[dict]:
    """Kubernetes resources in a file (skips kustomization.yaml, which has no metadata)."""
    return [d for d in yaml.safe_load_all(path.read_text()) if d and "metadata" in d]


BASE = {(d["kind"], d["metadata"]["name"]): d for f in (K8S / "base").glob("*.yaml") for d in _docs(f)}
GKE = {
    (d["kind"], d["metadata"]["name"]): d
    for f in (K8S / "overlays" / "gke").glob("*.yaml")
    for d in _docs(f)
    if "kind" in d
}
DEPLOYMENTS = [BASE[("Deployment", "api")], BASE[("Deployment", "frontend")]]


def _container(deployment: dict) -> dict:
    return deployment["spec"]["template"]["spec"]["containers"][0]


def _settings_env_names() -> set[str]:
    names = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if alias is not None:
            names.update(c.upper() for c in getattr(alias, "choices", [alias]) if isinstance(c, str))
    return names


# ---------- configuration ----------
def test_every_configmap_key_is_a_real_setting():
    unknown = set(BASE[("ConfigMap", "api-config")]["data"]) - _settings_env_names()
    assert unknown == set(), f"ConfigMap keys the app would silently ignore: {unknown}"


def test_configmaps_contain_no_secrets():
    for name in ("api-config", "frontend-config"):
        for key, value in BASE[("ConfigMap", name)]["data"].items():
            assert not re.search(r"KEY|SECRET|TOKEN|PASSWORD", key), key
            assert not re.search(r"(AIza|tvly-)[\w-]{6,}", value), key


def test_configmap_values_produce_valid_settings():
    data = BASE[("ConfigMap", "api-config")]["data"]
    settings = Settings(
        _env_file=None, llm_api_key="k", tavily_api_key="t", **{k.lower(): v for k, v in data.items()}
    )
    assert settings.app_env == "dev" and settings.cors_allow_origins == [] and settings.log_format == "json"
    prod = Settings(
        _env_file=None,
        llm_api_key="k",
        tavily_api_key="t",
        **{**{k.lower(): v for k, v in data.items()}, "app_env": "prod"},
    )  # what the GKE overlay sets
    assert prod.app_env == "prod"


def test_secret_example_has_placeholders_only_and_is_not_deployed():
    secret = _docs(K8S / "base" / "secret.example.yaml")[0]
    assert set(secret["stringData"].values()) == {"REPLACE_ME"}
    assert (
        "secret.example.yaml" not in (K8S / "base" / "kustomization.yaml").read_text().split("resources:")[1]
    )


def test_frontend_api_url_matches_the_api_service():
    url = BASE[("ConfigMap", "frontend-config")]["data"]["API_BASE_URL"]
    svc = BASE[("Service", "api")]
    ns = BASE[("Namespace", "travel-planner")]["metadata"]["name"]
    assert url == f"http://{svc['metadata']['name']}.{ns}.svc.cluster.local:{svc['spec']['ports'][0]['port']}"


# ---------- probes and ports ----------
def test_api_probes_use_real_routes_and_the_right_endpoints():
    routes = set(create_app().openapi()["paths"])  # included routers are nested in app.routes
    c = _container(BASE[("Deployment", "api")])
    assert c["livenessProbe"]["httpGet"]["path"] == "/api/v1/health"
    assert c["readinessProbe"]["httpGet"]["path"] == "/api/v1/health/ready"
    assert c["startupProbe"]["httpGet"]["path"] == "/api/v1/health"
    assert {"/api/v1/health", "/api/v1/health/ready"} <= routes


@pytest.mark.parametrize(
    "dockerfile,deployment", [("Dockerfile", "api"), ("frontend/Dockerfile", "frontend")]
)
def test_ports_and_user_match_the_image(dockerfile, deployment):
    text = (ROOT / dockerfile).read_text()
    exposed = int(re.search(r"^EXPOSE (\d+)", text, re.MULTILINE).group(1))
    uid = int(re.search(r"--uid (\d+)", text).group(1))
    d = BASE[("Deployment", deployment)]
    assert _container(d)["ports"][0]["containerPort"] == exposed
    assert d["spec"]["template"]["spec"]["securityContext"]["runAsUser"] == uid


def test_graceful_shutdown_fits_inside_the_grace_period():
    d = BASE[("Deployment", "api")]
    grace = d["spec"]["template"]["spec"]["terminationGracePeriodSeconds"]
    pre_stop = int(_container(d)["lifecycle"]["preStop"]["exec"]["command"][-1])
    uvicorn = int(
        re.search(r'"--timeout-graceful-shutdown", "(\d+)"', (ROOT / "Dockerfile").read_text()).group(1)
    )
    assert pre_stop + uvicorn < grace


# ---------- security ----------
@pytest.mark.parametrize("deployment", DEPLOYMENTS, ids=lambda d: d["metadata"]["name"])
def test_pod_and_container_security_context(deployment):
    pod = deployment["spec"]["template"]["spec"]
    c = _container(deployment)
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert pod["automountServiceAccountToken"] is False
    sc = c["securityContext"]
    assert sc["allowPrivilegeEscalation"] is False and sc["readOnlyRootFilesystem"] is True
    assert sc["capabilities"]["drop"] == ["ALL"]
    assert {"requests", "limits"} <= set(c["resources"])
    assert {"cpu", "memory"} <= set(c["resources"]["limits"])


def test_only_the_ui_is_exposed_publicly():
    for name in ("api", "frontend"):
        assert BASE[("Service", name)]["spec"]["type"] == "ClusterIP"
    ingress = GKE[("Ingress", "frontend")]
    assert ingress["spec"]["defaultBackend"]["service"]["name"] == "frontend"
    assert "rules" not in ingress["spec"]  # no path routes the internet to the API


def test_network_policy_defaults_to_deny_and_api_accepts_only_the_ui():
    deny = BASE[("NetworkPolicy", "default-deny")]
    assert deny["spec"]["podSelector"] == {} and set(deny["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    api = BASE[("NetworkPolicy", "api")]
    assert api["spec"]["ingress"][0]["from"] == [{"podSelector": {"matchLabels": {"app": "frontend"}}}]
    https = api["spec"]["egress"][1]
    assert https["ports"] == [{"port": 443, "protocol": "TCP"}]
    assert "169.254.169.254/32" in https["to"][0]["ipBlock"]["except"]


# ---------- scaling ----------
def test_hpa_scales_the_api_from_at_least_two_replicas():
    hpa = BASE[("HorizontalPodAutoscaler", "api")]
    assert hpa["spec"]["scaleTargetRef"]["name"] == "api"
    assert hpa["spec"]["minReplicas"] >= 2 and hpa["spec"]["maxReplicas"] > hpa["spec"]["minReplicas"]
    assert BASE[("Deployment", "api")]["spec"]["replicas"] == hpa["spec"]["minReplicas"]
    assert BASE[("PodDisruptionBudget", "api")]["spec"]["minAvailable"] < hpa["spec"]["minReplicas"]


# ---------- GKE overlay ----------
def test_gke_reads_secrets_from_secret_manager_files():
    spc = GKE[("SecretProviderClass", "api-secrets")]
    paths = re.findall(r'path: "(\w+)"', spc["spec"]["parameters"]["secrets"])
    assert set(paths) == {"GEMINI_API_KEY", "TAVILY_API_KEY"}  # file names = env names the app reads
    patch = GKE[("Deployment", "api")]
    env = patch["spec"]["template"]["spec"]["containers"][0]["env"]
    assert {"name": "SECRETS_DIR", "value": "/var/secrets"} in env


def test_gke_websocket_timeout_is_raised_for_streamlit():
    assert GKE[("BackendConfig", "frontend")]["spec"]["timeoutSec"] >= 600
