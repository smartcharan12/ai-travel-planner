"""Application configuration loaded from environment variables.

Every setting lives here so the rest of the code never calls ``os.getenv``
directly. Values come from (highest priority first):

1. real environment variables (Docker, Kubernetes, CI)
2. a local ``.env`` file (developer machine only, git-ignored)
3. the defaults below

Secrets use ``SecretStr`` so they print as ``**********`` if a Settings
object is ever logged or shown in a traceback.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    )

    # ---------- Application ----------
    app_name: str = "ai-travel-planner"
    app_env: Literal["local", "dev", "prod"] = "local"
    app_version: str = __version__
    # Injected at Docker build time by CI so /version shows the exact commit.
    git_sha: str = "unknown"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # ---------- LLM ----------
    llm_provider: LLMProvider = "gemini"
    llm_model: str = "gemini-2.5-flash"
    llm_api_key: SecretStr | None = None
    # Low temperature: we want consistent, grounded plans, not creative fiction.
    llm_temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)

    # ---------- Search ----------
    search_provider: SearchProvider = "tavily"
    tavily_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None
    search_timeout_seconds: float = Field(default=15, gt=0, le=60)
    search_max_results: int = Field(default=5, ge=1, le=10)

    # ---------- Workflow ----------
    # How many times the planner may ask the LLM to repair an invalid itinerary
    # before giving up. Bounded so a bad model cannot loop (and bill) forever.
    max_repair_attempts: int = Field(default=2, ge=0, le=5)

    @field_validator("llm_api_key", "tavily_api_key", "serper_api_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        """Treat ``LLM_API_KEY=`` (empty, as in .env.example) as 'not set'."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
            missing.append("LLM_API_KEY")
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
    """
    return Settings()
