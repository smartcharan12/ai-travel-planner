"""Static checks for Dockerfiles, compose, .dockerignore and the ELK configuration.

These do not replace running Docker (see the Stage 4 report), but they lock in the
security and consistency properties that are easy to break by accident.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
import yaml

from app.observability.logging import JsonFormatter

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = [ROOT / "Dockerfile", ROOT / "frontend" / "Dockerfile"]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
PIPELINE = (ROOT / "monitoring/elk/logstash/pipeline/travel-planner.conf").read_text()
TEMPLATE = json.loads((ROOT / "monitoring/elk/elasticsearch/travel-planner-logs.template.json").read_text())
MAPPED = TEMPLATE["template"]["mappings"]["properties"]


# ---------- Dockerfiles ----------
@pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_dockerfile_security_properties(dockerfile):
    text = dockerfile.read_text()
    users = re.findall(r"^USER\s+(\S+)", text, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}, "final stage must run as a non-root user"
    assert "HEALTHCHECK" in text
    assert re.search(r'^CMD \[".+"\]', text, re.MULTILINE), "CMD must use exec (JSON) form"
    assert not re.search(r"^COPY[^\n]*\.env", text, re.MULTILINE), ".env must never be copied"
    assert not re.search(r"(KEY|SECRET|TOKEN|PASSWORD)\s*=", text, re.IGNORECASE), "no secrets in the image"
    assert text.count("FROM ") >= 2, "multi-stage build keeps pip and caches out of the runtime image"
    assert ":latest" not in text


def test_api_image_installs_only_runtime_dependencies():
    runtime = (ROOT / "requirements.txt").read_text()
    assert "deepeval" not in runtime and "streamlit" not in runtime and "pytest" not in runtime
    assert "COPY app ./app" in (ROOT / "Dockerfile").read_text()


def test_dockerignore_excludes_secrets_and_bulk():
    entries = set((ROOT / ".dockerignore").read_text().split())
    assert {".env", ".env.*", ".git", ".venv", "tests", "evaluation"} <= entries


# ---------- compose ----------
def test_compose_never_contains_secret_values():
    for name, svc in COMPOSE["services"].items():
        env = svc.get("environment", {})
        for key in env:
            assert not re.search(r"(API_KEY|SECRET|PASSWORD|TOKEN)", key), f"{name} hard-codes {key}"


def test_api_reads_secrets_from_env_file_at_runtime_only():
    api = COMPOSE["services"]["api"]
    assert api["env_file"] == [{"path": ".env", "required": False}]


def test_published_ports_are_localhost_only():
    for name, svc in COMPOSE["services"].items():
        for port in svc.get("ports", []):
            assert port.startswith("127.0.0.1:"), f"{name} publishes {port} on all interfaces"


def test_elk_is_an_optional_profile_with_matching_versions():
    elk = ["elasticsearch", "logstash", "kibana", "elk-setup"]
    for name in elk:
        assert COMPOSE["services"][name]["profiles"] == ["elk"]
    versions = {
        COMPOSE["services"][n]["image"].split(":")[1] for n in ("elasticsearch", "logstash", "kibana")
    }
    assert len(versions) == 1, f"ELK versions must match: {versions}"
    assert all(":latest" not in s.get("image", ":x") for s in COMPOSE["services"].values())


def test_frontend_reaches_api_by_service_name_and_waits_for_health():
    fe = COMPOSE["services"]["frontend"]
    assert fe["environment"]["API_BASE_URL"] == "http://api:8000"
    assert fe["depends_on"]["api"]["condition"] == "service_healthy"


def test_log_file_is_shared_from_api_to_logstash():
    api, ls = COMPOSE["services"]["api"], COMPOSE["services"]["logstash"]
    log_file = api["environment"]["LOG_FILE"]
    assert f"app-logs:{Path(log_file).parent}" in api["volumes"]
    assert f"app-logs:{Path(log_file).parent}:ro" in ls["volumes"]  # Logstash only reads
    assert f'path => "{log_file}"' in PIPELINE


def test_logstash_template_mount_matches_pipeline():
    mount = next(v for v in COMPOSE["services"]["logstash"]["volumes"] if "template" in v)
    assert mount.split(":")[1] in PIPELINE


# ---------- Logstash <-> Elasticsearch <-> application log fields ----------
def test_pipeline_parses_json_and_writes_the_templated_index():
    assert "codec => json" in PIPELINE
    assert 'index => "travel-planner-logs-%{+YYYY.MM.dd}"' in PIPELINE
    assert TEMPLATE["index_patterns"] == ["travel-planner-logs-*"]


def test_logstash_type_conversions_match_the_mapping():
    converted = re.findall(r'"(\w+)" => "(integer|float)"', PIPELINE)
    assert converted
    for field, _ in converted:
        assert MAPPED[field]["type"] in {"integer", "long", "float"}, field


def test_every_non_string_field_the_app_logs_has_an_explicit_mapping(client, goa_payload, caplog):
    """Run a real demo request and check the JSON it logs against the index template.

    Strings fall back to the keyword dynamic template; numbers and booleans must be
    mapped explicitly so Elasticsearch never infers conflicting types."""
    caplog.set_level(logging.INFO)
    client.post("/api/v1/plan", json=goa_payload)
    client.post("/api/v1/plan", json={"destination": "Goa", "num_days": 99, "budget": 1})
    formatter = JsonFormatter("api")
    docs = [json.loads(formatter.format(r)) for r in caplog.records if getattr(r, "event_type", None)]
    assert {d["event_type"] for d in docs} >= {
        "request_completed",
        "llm_call",
        "search_call",
        "plan_completed",
    }
    unmapped = sorted(
        {
            key
            for d in docs
            for key, value in d.items()
            if key != "timestamp" and value is not None and not isinstance(value, str) and key not in MAPPED
        }
    )
    assert unmapped == [], f"add these fields to the index template: {unmapped}"
