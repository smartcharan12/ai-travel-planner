"""Settings parsing and the in-memory metrics registry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.observability.metrics import MetricsRegistry


def test_blank_api_key_counts_as_missing(make_settings):
    settings = make_settings(llm_api_key="", tavily_api_key="   ")
    assert settings.llm_api_key is None
    assert settings.missing_secrets() == ["GEMINI_API_KEY", "TAVILY_API_KEY"]


def test_keys_are_hidden_when_printed(make_settings):
    settings = make_settings(llm_api_key="super-secret-value")
    assert "super-secret-value" not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "super-secret-value"


def test_serper_needs_its_own_key(make_settings):
    settings = make_settings(search_provider="serper", llm_api_key="k")
    assert settings.missing_secrets() == ["SERPER_API_KEY"]


def test_demo_providers_need_no_keys(make_settings):
    settings = make_settings(llm_provider="fake", search_provider="mock")
    assert settings.missing_secrets() == []
    assert settings.is_demo


def test_settings_read_environment_variables(monkeypatch, make_settings):
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("SEARCH_MAX_RESULTS", "7")
    settings = make_settings()
    assert settings.llm_model == "gemini-2.5-pro"
    assert settings.search_max_results == 7  # string from env -> int


def test_invalid_setting_fails_fast(make_settings):
    with pytest.raises(ValidationError):
        make_settings(llm_temperature=3.0)


def test_metrics_counters_and_timings():
    registry = MetricsRegistry()
    registry.increment("calls", {"provider": "tavily", "a": "1"})
    registry.increment("calls", {"a": "1", "provider": "tavily"})  # label order irrelevant
    registry.observe_ms("latency", 100)
    registry.observe_ms("latency", 300)
    snap = registry.snapshot()
    assert snap["counters"] == {"calls{a=1,provider=tavily}": 2}
    assert snap["timings_ms"]["latency"] == {"count": 2, "avg": 200.0, "max": 300.0}


def test_env_example_parses_as_a_real_env_file():
    # Regression: `cp .env.example .env` must give a working (keyless) configuration.
    from pathlib import Path

    from app.config import Settings

    example = Path(__file__).resolve().parents[2] / ".env.example"
    settings = Settings(_env_file=example)
    assert settings.llm_api_key is None and settings.log_file is None
    assert settings.llm_input_cost_per_million_usd is None
