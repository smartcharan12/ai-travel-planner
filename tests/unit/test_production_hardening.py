"""Stage 5 hardening: environments, file secrets, CORS, rate and concurrency limits."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.api.limits import ConcurrencyLimiter, SlidingWindowLimiter
from app.config import Settings, get_settings
from app.main import create_app


# ---------- configuration ----------
def test_secrets_dir_files_are_read_like_secret_manager_mounts(tmp_path, monkeypatch):
    (tmp_path / "GEMINI_API_KEY").write_text("from-secret-manager\n")
    (tmp_path / "TAVILY_API_KEY").write_text("tvly-from-file")
    monkeypatch.setenv("SECRETS_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path.parent)  # no developer .env
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.llm_api_key.get_secret_value() == "from-secret-manager"
        assert settings.missing_secrets() == []
    finally:
        get_settings.cache_clear()


def test_env_var_wins_over_secret_file(tmp_path, monkeypatch):
    (tmp_path / "GEMINI_API_KEY").write_text("file-value")
    monkeypatch.setenv("GEMINI_API_KEY", "env-value")
    assert Settings(_env_file=None, _secrets_dir=str(tmp_path)).llm_api_key.get_secret_value() == "env-value"


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"demo_mode": True}, "DEMO_MODE"),
        ({"cors_allow_origins": "*"}, "CORS_ALLOW_ORIGINS"),
        ({"log_format": "text"}, "LOG_FORMAT"),
    ],
)
def test_production_guard_refuses_unsafe_settings(overrides, message):
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, app_env="prod", llm_api_key="k", tavily_api_key="t", **overrides)


def test_valid_production_settings_and_other_environments():
    assert Settings(_env_file=None, app_env="prod", llm_api_key="k", tavily_api_key="t").app_env == "prod"
    assert Settings(_env_file=None, app_env="test", demo_mode=True).is_demo  # demo is fine outside prod


def test_cors_origins_accept_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://a.example, https://b.example")
    assert Settings(_env_file=None).cors_allow_origins == ["https://a.example", "https://b.example"]


# ---------- CORS ----------
def _preflight(client, origin):
    return client.options(
        "/api/v1/plan",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


def test_cors_is_off_by_default(client):
    resp = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_cors_allows_only_configured_origins(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://ui.example")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert (
            _preflight(client, "https://ui.example").headers["access-control-allow-origin"]
            == "https://ui.example"
        )
        assert "access-control-allow-origin" not in _preflight(client, "https://evil.example").headers
    finally:
        get_settings.cache_clear()


# ---------- rate limiting ----------
def test_sliding_window_limiter():
    limiter = SlidingWindowLimiter(window_seconds=60)
    assert limiter.check("ip", 2, now=0) is None
    assert limiter.check("ip", 2, now=1) is None
    assert limiter.check("ip", 2, now=2) == pytest.approx(58)  # oldest hit frees at t=60
    assert limiter.check("other-ip", 2, now=2) is None  # per client
    assert limiter.check("ip", 2, now=60.5) is None  # window moved on


def test_api_returns_429_with_retry_after(client, make_settings, goa_payload):
    client.app.dependency_overrides[get_settings] = lambda: make_settings(
        demo_mode=True, rate_limit_per_minute=2
    )
    assert [client.post("/api/v1/research", json=goa_payload).status_code for _ in range(2)] == [200, 200]
    resp = client.post("/api/v1/plan", json=goa_payload)  # same client, shared budget across both endpoints
    assert resp.status_code == 429
    error = resp.json()["error"]
    assert error["code"] == "RATE_LIMITED" and error["details"]["reason"] == "rate"
    assert int(resp.headers["Retry-After"]) > 0


def test_rate_limit_zero_disables_it(client, make_settings, goa_payload):
    client.app.dependency_overrides[get_settings] = lambda: make_settings(
        demo_mode=True, rate_limit_per_minute=0
    )
    assert all(client.post("/api/v1/research", json=goa_payload).status_code == 200 for _ in range(3))


def test_health_endpoints_are_never_rate_limited(client, make_settings):
    client.app.dependency_overrides[get_settings] = lambda: make_settings(
        demo_mode=True, rate_limit_per_minute=1
    )
    assert all(client.get("/api/v1/health").status_code == 200 for _ in range(5))


# ---------- concurrency ----------
def test_concurrency_limiter():
    async def scenario():
        limiter = ConcurrencyLimiter()
        assert await limiter.try_acquire(1)
        assert not await limiter.try_acquire(1)
        await limiter.release()
        assert await limiter.try_acquire(1)
        assert await limiter.try_acquire(0)  # 0 = unlimited

    asyncio.run(scenario())


def test_busy_replica_returns_429_and_releases_slots(client, make_settings, goa_payload):
    client.app.dependency_overrides[get_settings] = lambda: make_settings(
        demo_mode=True, max_concurrent_plans=1
    )
    client.app.state.concurrency.active = 1  # simulate one plan already running
    resp = client.post("/api/v1/plan", json=goa_payload)
    assert resp.status_code == 429 and resp.json()["error"]["details"]["reason"] == "busy"
    client.app.state.concurrency.active = 0
    assert client.post("/api/v1/plan", json=goa_payload).status_code == 200
    assert client.app.state.concurrency.active == 0  # slot released after the request
