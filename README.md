# AI Travel Planner — LLMOps Platform

Researched, validated and budgeted travel itineraries: FastAPI + LangGraph + Gemini + real-time web search,
with structured logging, ELK, DeepEval, Docker, Kubernetes and a GCP deployment guide.

> **Build status: Stage 1 of 5 complete.** The API, configuration and data contracts are built and tested.
> The AI planner arrives in Stage 2. `POST /api/v1/plan` currently validates the request and then
> returns `501 PLANNER_NOT_IMPLEMENTED`, on purpose, rather than a fake itinerary.

| Stage | Contents | Status |
|---|---|---|
| 1 | Architecture, structure, config, data models, FastAPI | ✅ done, 54 tests passing |
| 2 | LLM, search tools, LangChain, LangGraph workflow, generation, budget engine, optimizer | ⏳ next |
| 3 | Streamlit frontend, integration tests, DeepEval | ⏳ |
| 4 | Structured logging, ELK, Docker, Kubernetes, GCP, CI/CD | ⏳ |
| 5 | Full documentation set, final audit | ⏳ |

## Start here

1. [ARCHITECTURE.md](ARCHITECTURE.md): the whole system, diagrams, design decisions, roadmap
2. [docs/03_configuration.md](docs/03_configuration.md): settings and secrets
3. [docs/12_data_models.md](docs/12_data_models.md): the Pydantic contracts
4. [docs/11_api.md](docs/11_api.md): endpoints, errors, request lifecycle

## Run locally (Stage 1)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # keys not needed yet
.venv/bin/uvicorn app.main:app --reload
# open http://localhost:8000/docs
.venv/bin/pytest -q             # run the tests
.venv/bin/ruff check .          # lint
```

## License

MIT, see [LICENSE](LICENSE).
