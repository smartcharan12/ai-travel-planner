"""Static checks for the GitHub Actions workflows (security and cost rules from docs/26_cicd.md)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> tuple[dict, str]:
    text = (WORKFLOWS / name).read_text()
    data = yaml.safe_load(text)
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 parses the key `on` as True
    return data, text


def test_no_credentials_are_written_into_any_workflow():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        assert not re.search(r"(AIza|tvly-)[\w-]{10,}", text), path.name
        assert '"type": "service_account"' not in text, path.name


def test_ci_needs_no_secrets_and_cannot_write():
    ci, text = _load("ci.yml")
    assert "secrets." not in text
    assert ci["permissions"] == {"contents": "read"}
    assert "pull_request" in ci["on"]


def test_ci_runs_lint_tests_audit_and_manifest_validation():
    ci, text = _load("ci.yml")
    assert {"test", "dependency-audit", "manifests", "images"} <= set(ci["jobs"])
    for command in (
        "ruff check",
        "pytest tests/unit",
        "pytest tests/integration",
        "pip-audit",
        "kubeconform",
    ):
        assert command in text, command
    assert ci["jobs"]["images"]["if"] == "github.event_name != 'pull_request'"  # images on main only


def test_deploy_uses_short_lived_oidc_credentials_and_waits_for_ci():
    deploy, text = _load("deploy.yml")
    assert deploy["permissions"]["id-token"] == "write"
    assert deploy["on"]["workflow_run"]["workflows"] == ["CI"]
    assert "github.event.workflow_run.conclusion == 'success'" in deploy["jobs"]["deploy"]["if"]
    assert "workload_identity_provider" in text
    assert (
        re.search(r"^\s+credentials_json:", text, re.MULTILINE) is None
    )  # key-file option stays commented out
    assert deploy["jobs"]["deploy"]["environment"] == "production"


def test_live_evaluation_is_manual_only():
    live, _ = _load("eval-live.yml")
    assert set(live["on"]) == {"workflow_dispatch"}
