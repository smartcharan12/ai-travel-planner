# 03 — Configuration and secrets (Phase 3)

Files: [`app/config.py`](../app/config.py), [`.env.example`](../.env.example), [`pyproject.toml`](../pyproject.toml),
[`requirements.txt`](../requirements.txt), [`requirements-dev.txt`](../requirements-dev.txt)

## WHAT

One `Settings` class that reads every configurable value (API keys, model name, timeouts, which search provider)
from environment variables, checks their types, and hands a single object to the rest of the app.

## WHY

The same code must run on your laptop, in Docker, in CI (no keys) and on GKE (keys from Secret Manager). Only
the *environment* differs. If code read `os.getenv("LLM_TIMEOUT")` in ten places you would get:

- a string `"60"` where a number was expected, discovered only at runtime;
- no single list of what the app needs;
- a real risk of printing a key in a log.

## INPUT

Environment variables, from (highest priority first): the real process environment → a `.env` file in the
current directory → defaults in the class. Names are case-insensitive: `LLM_MODEL` fills `llm_model`.

## LOGIC

1. `Settings()` (pydantic-settings) collects the values and **converts types**: `"7"` → `7`, `"0.3"` → `0.3`.
2. **Validates ranges**: `llm_temperature` must be 0–1, `search_max_results` 1–10. A bad value raises at
   startup, not at 2 a.m. in the middle of a request.
3. `_blank_secret_is_none` turns `LLM_API_KEY=` (the empty line in `.env.example`) into `None` = "not set".
4. Secrets are `SecretStr`: `print(settings)` shows `llm_api_key=SecretStr('**********')`. Code that really
   needs the key calls `.get_secret_value()`, which is easy to search for in review.
5. `missing_secrets()` lists env var *names* the chosen providers need but don't have. Note the app still
   **starts** without keys. That is deliberate: `/health` can then tell you what is wrong, and the
   Kubernetes readiness probe keeps the pod out of rotation (Stage 4).
6. `get_settings()` is wrapped in `@lru_cache`, so `.env` is parsed once per process.

## OUTPUT

A `Settings` object, e.g. `settings.llm_model == "gemini-2.5-flash"`, `settings.is_demo == False`.

## CONNECTION

- `app/api/routes.py` receives it via `Depends(get_settings)` for `/version` and `/health/ready`.
- Stage 2: the LLM factory and search factory read provider, model, keys and timeouts from it.
- Tests replace it: `app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, ...)`.

## CODE (the important part)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    llm_provider: Literal["gemini", "fake"] = "gemini"
    llm_api_key: SecretStr | None = None
    llm_temperature: float = Field(default=0.3, ge=0.0, le=1.0)

    def missing_secrets(self) -> list[str]:
        missing = []
        if self.llm_provider == "gemini" and self.llm_api_key is None:
            missing.append("LLM_API_KEY")
        ...
        return missing
```

## EXAMPLE

```bash
$ LLM_TEMPERATURE=3 .venv/bin/python -c "from app.config import Settings; Settings()"
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
llm_temperature
  Input should be less than or equal to 1 ...
```

## The "demo" providers

`LLM_PROVIDER=fake` and `SEARCH_PROVIDER=mock` select offline stand-ins (built in Stage 2) so tests, CI and a
first local run need no paid keys. Responses produced that way carry `metadata.is_demo = true` and are
**never** presented as real research.

## Dependency files

- `requirements.txt`: exact versions (`fastapi==0.142.2`) so Docker, CI and your laptop install identical
  code. New libraries are added in the stage that first uses them.
- `requirements-dev.txt`: adds pytest and ruff, which the production image does not need.
- `pyproject.toml`: project metadata plus tool config (ruff rules, pytest markers).

## BEGINNER EXPLANATION

Think of `.env` as the settings screen of an app and `Settings` as the receptionist who reads that screen
once in the morning, checks that nothing is filled in nonsensically, and answers everyone else's questions
("which model are we using?") so they never touch the screen themselves. The secret keys are kept in a sealed
envelope (`SecretStr`). You have to deliberately open it (`get_secret_value()`), so it never gets read out by
accident.

## Common mistakes

| Mistake | Consequence | Fix |
|---|---|---|
| Committing `.env` | Keys leak publicly; bots scrape GitHub within minutes | `.gitignore` already excludes it; rotate any leaked key immediately |
| Quoting with spaces: `LLM_MODEL = "x"` | Variable not recognised | `NAME=value`, no spaces around `=` |
| Running from another directory | `.env` not found (it is read from the *current* directory) | Run commands from the repo root |
| Editing `.env` while the server runs | Old values still used (cached) | Restart the server |
