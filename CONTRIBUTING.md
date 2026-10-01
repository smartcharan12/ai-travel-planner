# Contributing

1. `python3 -m venv .venv && .venv/bin/pip install -r requirements-eval.txt`
2. Create a branch. Keep changes small and explain *why* in the PR description.
3. Before pushing:
   ```bash
   .venv/bin/ruff check . && .venv/bin/ruff format --check .
   .venv/bin/pytest -q
   .venv/bin/python -m evaluation.runner --mode demo --report-only   # if you touched prompts or planning
   ```
4. Rules this codebase follows:
   - The LLM never does arithmetic, writes titles or invents prices; code does.
   - New places can enter a plan only through verified research ids.
   - Every new setting goes into `app/config.py` and `.env.example`; Kubernetes ConfigMap keys must be real settings (tested).
   - Never commit secrets; `.env` is git-ignored. Use `secret.example.yaml` placeholders only.
   - Don't report something as working unless it was run; mark it NOT RUN or DOCUMENTED ONLY.
   - Bump `PLANNER_PROMPT_VERSION` / `PROMPT_VERSION` when a prompt changes, and re-run the evaluation.
5. CI (`.github/workflows/ci.yml`) must pass; live evaluation is triggered manually by maintainers.
