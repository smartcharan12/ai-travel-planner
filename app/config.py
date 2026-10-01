"""Application configuration loaded from environment variables.

Every setting lives here so the rest of the code never calls ``os.getenv``
directly. Values come from (highest priority first):

1. real environment variables (Docker, Kubernetes ConfigMap/Secret, CI)
2. a local ``.env`` file (developer machine only, git-ignored)
3. secret files in ``SECRETS_DIR`` (one file per variable, e.g. ``/var/secrets/GEMINI_API_KEY``),
   which is how Google Secret Manager secrets are mounted on GKE
4. the defaults below

Environments (``APP_ENV``): ``local`` (developer laptop), ``test`` (automated tests/CI),
``dev`` (shared cluster), ``prod`` (production). ``DEMO_MODE`` is separate: it switches
providers to offline stand-ins and is refused in ``prod``.

Secrets use ``SecretStr`` so they print as ``**********`` if a Settings
object is ever logged or shown in a traceback.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app import __version__

LLMProvider = Literal["gemini", "fake"]
SearchProvider = Literal["tavily", "serper", "mock"]


class Settings(BaseSettings):
    """Typed, validated view of the process environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # unrelated env vars (PATH, HOME, ...) are not errors
        case_sensitive=False,
        populate_by_name=True,  # lets tests pass llm_api_key=... by field name
    )

    # ---------- Application ----------
    app_name: str = "ai-travel-planner"
    app_env: Literal["local", "test", "dev", "prod"] = "local"
    app_version: str = __version__
    # Injected at Docker build time by CI so /version shows the exact commit.
    git_sha: str = "unknown"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # json = one JSON object per line (for Logstash/Cloud Logging); text = readable local output.
    log_format: Literal["json", "text"] = "json"
    # Optional extra destination; docker-compose sets it so Logstash can tail the file.
    log_file: str | None = None

    # ---------- Demo mode ----------
    # Explicit opt-in only. The app never switches to demo data by itself
    # when a key is missing; it reports a configuration error instead.
    demo_mode: bool = False

    # ---------- LLM ----------
    llm_provider: LLMProvider = "gemini"
    llm_model: str = "gemini-2.5-flash"
    # Read from GEMINI_API_KEY (preferred) or the older LLM_API_KEY name.
    llm_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "LLM_API_KEY", "llm_api_key")
    )
    # Low temperature: we want consistent, grounded plans, not creative fiction.
    llm_temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    # Research extraction copies facts out of sources; zero creativity wanted.
    research_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)
    # Transport-level retries (network blips, 5xx) done inside the Gemini SDK.
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # Extra attempts when the model answers but the JSON is malformed/invalid.
    llm_output_retries: int = Field(default=1, ge=0, le=3)
    # Optional prices (USD per 1M tokens) used ONLY to estimate cost in logs.
    # Left unset by default: provider prices change, and a stale hard-coded
    # price would produce confident but wrong cost numbers. Unset -> cost is null.
    llm_input_cost_per_million_usd: float | None = Field(default=None, ge=0)
    llm_output_cost_per_million_usd: float | None = Field(default=None, ge=0)

    # ---------- Search ----------
    search_provider: SearchProvider = "tavily"
    tavily_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None
    search_timeout_seconds: float = Field(default=15, gt=0, le=60)
    search_max_results: int = Field(default=5, ge=1, le=10)
    tavily_search_depth: Literal["basic", "advanced"] = "basic"
    # Longer snippets = more evidence for the LLM but more tokens (= cost).
    search_max_content_chars: int = Field(default=1200, ge=200, le=5000)

    # ---------- Research ----------
    max_entities_per_category: int = Field(default=8, ge=1, le=20)

    # ---------- HTTP protection ----------
    # Browser origins allowed to call the API directly. Empty = CORS disabled, which is right
    # for this project: the Streamlit UI calls the API from its server, not from the browser.
    # NoDecode: let the validator below parse the raw env string (comma list or JSON list).
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Per-client requests per minute on the expensive endpoints (/plan, /research); 0 = off.
    rate_limit_per_minute: int = Field(default=20, ge=0, le=10_000)
    # Plans running at once in ONE replica; extra requests get 429 instead of queueing
    # (protects LLM quota, cost and memory). 0 = unlimited.
    max_concurrent_plans: int = Field(default=8, ge=0, le=1_000)

    # ---------- Workflow ----------
    # How many times the planner may ask the LLM to repair an invalid itinerary
    # before giving up. Bounded so a bad model cannot loop (and bill) forever.
    max_repair_attempts: int = Field(default=2, ge=0, le=5)

    @field_validator(
        "llm_api_key",
        "tavily_api_key",
        "serper_api_key",
        "log_file",
        "llm_input_cost_per_million_usd",
        "llm_output_cost_per_million_usd",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        """Treat ``GEMINI_API_KEY=`` (empty, as in .env.example) as 'not set'."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept 'https://a.com,https://b.com' as well as a JSON list."""
        if isinstance(value, str):
            if value.strip().startswith("["):
                return json.loads(value)
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _production_guard(self) -> Settings:
        """Refuse unsafe combinations in production at start-up, not at the first request."""
        if self.app_env != "prod":
            return self
        problems = []
        if self.demo_mode or self.is_demo:  # demo_mode is applied by a later validator
            problems.append("DEMO_MODE / fake providers are not allowed in prod")
        if "*" in self.cors_allow_origins:
            problems.append("CORS_ALLOW_ORIGINS must not contain '*' in prod")
        if self.log_format != "json":
            problems.append("LOG_FORMAT must be json in prod (Cloud Logging parses it)")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _apply_demo_mode(self) -> Settings:
        """DEMO_MODE=true switches BOTH providers to offline stand-ins.

        Mixing one fake and one real provider is rejected: the demo LLM only
        understands demo search data, and a half-real response would be
        impossible to label honestly.
        """
        if self.demo_mode:
            self.llm_provider = "fake"
            self.search_provider = "mock"
        if (self.llm_provider == "fake") != (self.search_provider == "mock"):
            raise ValueError(
                "LLM_PROVIDER=fake and SEARCH_PROVIDER=mock must be used together (or set DEMO_MODE=true)"
            )
        return self

    @property
    def is_demo(self) -> bool:
        """True when any provider is an offline stand-in rather than a real API."""
        return self.llm_provider == "fake" or self.search_provider == "mock"

    def missing_secrets(self) -> list[str]:
        """Return the env var names that the selected providers need but lack.

        The app still *starts* without them (so /health can explain what is
        wrong); the readiness probe and the planner refuse to run instead.
        """
        missing: list[str] = []
        if self.llm_provider == "gemini" and self.llm_api_key is None:
            missing.append("GEMINI_API_KEY")
        if self.search_provider == "tavily" and self.tavily_api_key is None:
            missing.append("TAVILY_API_KEY")
        if self.search_provider == "serper" and self.serper_api_key is None:
            missing.append("SERPER_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    """Build Settings once per process and reuse it.

    Used as a FastAPI dependency, so tests can swap it with
    ``app.dependency_overrides[get_settings] = lambda: Settings(...)``.
    ``SECRETS_DIR`` (set on GKE) adds file-based secrets from Secret Manager.
    """
    secrets_dir = os.getenv("SECRETS_DIR")
    return Settings(_secrets_dir=secrets_dir) if secrets_dir else Settings()
