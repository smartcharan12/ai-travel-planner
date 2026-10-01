"""HTTP-level tests: status codes, response shapes and error format."""

from __future__ import annotations

from app.config import get_settings


def test_health_is_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_every_response_carries_a_request_id(client):
    resp = client.get("/api/v1/health")
    assert len(resp.headers["X-Request-ID"]) >= 8


def test_safe_incoming_request_id_is_reused(client):
    resp = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-12345"})
    assert resp.headers["X-Request-ID"] == "trace-abc-12345"


def test_unsafe_incoming_request_id_is_replaced(client):
    resp = client.get("/api/v1/health", headers={"X-Request-ID": 'bad id" injected'})
    assert resp.headers["X-Request-ID"] != 'bad id" injected'


def test_readiness_ok_in_demo_mode(client):
    assert client.get("/api/v1/health/ready").status_code == 200


def test_readiness_reports_missing_key_names_not_values(client, make_settings):
    client.app.dependency_overrides[get_settings] = lambda: make_settings(
        llm_provider="gemini", search_provider="tavily", tavily_api_key="tvly-secret"
    )
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 503
    assert resp.json()["checks"]["config"] == "missing: GEMINI_API_KEY"
    assert "tvly-secret" not in resp.text


def test_version_reports_configuration(client):
    body = client.get("/api/v1/version").json()
    assert body["llm_provider"] == "fake"
    assert body["search_provider"] == "mock"
    assert body["version"]


def test_metrics_count_requests(client):
    client.get("/api/v1/health")
    body = client.get("/api/v1/metrics").json()
    key = "http_requests_total{method=GET,route=/api/v1/health,status=200}"
    assert body["counters"][key] >= 1
    assert "http_request_latency{method=GET,route=/api/v1/health}" in body["timings_ms"]


def test_plan_rejects_invalid_body_with_field_details(client, goa_payload):
    goa_payload["num_days"] = 99
    resp = client.post("/api/v1/plan", json=goa_payload)
    assert resp.status_code == 422
    error = resp.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["request_id"] == resp.headers["X-Request-ID"]
    assert error["details"]["fields"][0]["field"] == "num_days"


def test_plan_rejects_malformed_json(client):
    resp = client.post("/api/v1/plan", content="{not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_research_returns_labelled_demo_research(client, goa_payload):
    # Stage 2 behaviour, now served at /research (/plan returns the itinerary since Stage 3).
    resp = client.post("/api/v1/research", json=goa_payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "research"
    assert body["data_mode"] == "demo"
    assert body["metadata"]["is_demo"] is True
    assert "DEMO DATA" in body["notice"]
    assert body["request_id"] == resp.headers["X-Request-ID"]
    assert body["research"]["attractions"], "demo pipeline should yield attractions"


def test_unexpected_errors_do_not_leak_details(client):
    @client.app.get("/boom")
    def boom():
        raise RuntimeError("password=hunter2 at /srv/internal/path.py")

    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in resp.text
