# Interview guide

Final edition (Stage 5). Every question has **Short** (say it), **Detail** (understand it) and **Here** (how it
applies to this project). Answers are tied to what was actually built and verified; where something was not run,
the answer says so.

Sections: Python 25 · FastAPI 20 · LLM 25 · LangChain 20 · LangGraph 20 · RAG/Grounding 20 · Prompt Engineering 20 ·
LLM evaluation 20 · DeepEval 20 · Docker 25 · Docker Compose 15 · Kubernetes 30 · GCP/GKE 30 · CI/CD 25 ·
ELK 20 + Observability 15 (ELK/Observability 35) · System Design 30 · Security 20 · Project-specific 40.

---

## Python (25)

**1. What are type hints and why use them everywhere?**
Short: annotations of expected types.
Detail: Python doesn't enforce them by default, but tools do; Pydantic and FastAPI use them to validate and convert at runtime.
Here: every function and schema is typed; FastAPI derives validation and docs from them.

**2. What is a virtual environment?**
Short: an isolated set of packages per project.
Detail: prevents version conflicts with other projects and the system Python.
Here: `.venv/` locally; `/opt/venv` inside the images.

**3. Why pin exact dependency versions?**
Short: reproducible installs.
Detail: unpinned dependencies can change between CI and production and break or introduce vulnerabilities.
Here: `==` pins in all requirements files; `pip-audit` checks them.

**4. What is async/await?**
Short: cooperative concurrency for I/O-bound work.
Detail: while one coroutine waits on the network, the event loop runs others on the same thread.
Here: the five searches run concurrently; `/plan` awaits the planner.

**5. When does async not help?**
Short: CPU-bound work.
Detail: a long computation blocks the event loop; use processes or offload it.
Here: our CPU work is about 30 ms per plan; waiting on external APIs dominates.

**6. Dataclass vs Pydantic model?**
Short: a plain container vs a validating, parsing model.
Detail: use Pydantic at trust boundaries, dataclasses for simple internal records.
Here: `RequestStats`, `CategoryResults` are dataclasses; API and LLM I/O are Pydantic.

**7. What does `functools.lru_cache` do here?**
Short: builds Settings once per process.
Detail: caches results by arguments; `cache_clear()` resets it (used in tests).
Here: `get_settings()`.

**8. What is a ContextVar?**
Short: a value private to the current task or request.
Detail: safe with asyncio, unlike thread-locals; child tasks get a copy of the context.
Here: `request_id_var` and `RequestStats` correlate all logs of a request.

**9. What does `from __future__ import annotations` do?**
Short: stores annotations as strings, evaluated lazily.
Detail: enables forward references and avoids import-time evaluation costs.
Here: at the top of every module.

**10. How do you chain exceptions?**
Short: `raise NewError(...) from exc`.
Detail: preserves the original cause (`__cause__`) for logs while exposing a clean error.
Here: `httpx.ReadTimeout` becomes `SearchTimeoutError`.

**11. Why custom exception classes?**
Short: callers handle meaning, not library details.
Detail: each carries a stable code, an HTTP status and a safe message.
Here: `app/core/exceptions.py`.

**12. What is a context manager?**
Short: an object for `with`, guaranteeing cleanup.
Detail: `__enter__`/`__exit__`, `@contextmanager`, or async variants.
Here: `async with httpx.AsyncClient(...)` closes connections even on errors.

**13. What is a generator, and a `yield` dependency?**
Short: a function that pauses at `yield` and resumes later.
Detail: FastAPI runs the code after `yield` once the response is done.
Here: `enforce_limits` releases the concurrency slot in `finally`.

**14. What is an abstract base class?**
Short: an interface subclasses must implement.
Detail: instantiating without implementing abstract methods raises an error.
Here: `SearchProvider.search` for Tavily, Serper and the demo provider.

**15. What is `StrEnum`?**
Short: an enum whose members are strings.
Detail: serialises naturally to JSON and compares equal to its string value.
Here: `TravelStyle`, `ActivityType`, `GenericActivity`.

**16. How does logging work?**
Short: loggers send records to handlers, which format them.
Detail: configure the root logger once; modules call `logging.getLogger(__name__)`.
Here: `configure_logging` installs the JSON formatter on stdout and an optional file.

**17. What is the GIL and does it matter here?**
Short: one thread executes Python bytecode at a time.
Detail: it limits CPU-bound threading, not I/O waiting.
Here: I/O-bound service, so we scale with replicas, not threads.

**18. How do you make a module runnable?**
Short: an `if __name__ == "__main__":` block, run with `python -m`.
Detail: `-m` sets up the package path correctly.
Here: `python -m evaluation.runner`, `python -m scripts.run_research`.

**19. What is a pytest fixture?**
Short: reusable setup injected by parameter name.
Detail: scopes (function, module, session) control reuse.
Here: `client`, `goa_payload`, `make_settings` in `tests/conftest.py`.

**20. What is monkeypatching?**
Short: temporarily replacing attributes or environment variables in a test.
Detail: undone automatically after the test.
Here: env vars in settings tests; replacing `api_client.plan_trip` in UI tests.

**21. What is `pytest.mark.parametrize`?**
Short: run one test over many inputs.
Detail: each input is reported as a separate test.
Here: injection-shaped destinations, error mappings, both Dockerfiles.

**22. How do you test async code without a plugin?**
Short: call `asyncio.run(...)` inside a sync test.
Detail: simple and explicit; a fresh event loop per call.
Here: planner, LLM-client and limiter tests.

**23. What is Ruff?**
Short: a fast linter and formatter.
Detail: replaces flake8, isort and black in one tool.
Here: CI fails on lint errors or formatting drift.

**24. Why `json.dumps(default=str)` in the log formatter?**
Short: never crash logging on unexpected types.
Detail: dates and enums are turned into strings instead of raising.
Here: `JsonFormatter.format`.

**25. How do you avoid mutable default arguments?**
Short: use `None` or a factory.
Detail: a default list is shared between calls and leaks state.
Here: Pydantic fields use `Field(default_factory=list)`.

## FastAPI (20)

**1. What is FastAPI?**
Short: a Python web framework built on Starlette and Pydantic.
Detail: type hints define validation, serialisation and the OpenAPI schema.
Here: `app/main.py`, `app/api/routes.py`.

**2. How is the request body validated?**
Short: it's parsed into the annotated Pydantic model; failures return 422.
Detail: validation runs before the route function, so the route only sees valid data.
Here: `TravelRequest`; our handler reshapes 422 into the standard error format with field names.

**3. What is `response_model`?**
Short: the schema used to validate and document the response.
Detail: filters and checks what you return.
Here: `TravelResponse` for `/plan`, `ResearchResponse` for `/research`.

**4. What is dependency injection?**
Short: `Depends(fn)` lets FastAPI construct and pass objects.
Detail: dependencies can be overridden in tests with `app.dependency_overrides`.
Here: `get_settings`, `get_planner`, `enforce_limits`.

**5. Why an application factory?**
Short: fresh, fully wired apps for each test or process.
Detail: avoids global state shared between tests.
Here: `create_app()`.

**6. What is middleware?**
Short: code that wraps every request.
Detail: runs before and after the route, including on errors.
Here: request id, stats context, metrics, `request_completed` log.

**7. How are exceptions turned into responses?**
Short: exception handlers registered per type.
Detail: more specific handlers win; a catch-all `Exception` handler covers surprises.
Here: domain errors → their code and status; validation → 422; unknown → generic 500.

**8. Why not return exception messages?**
Short: they can leak secrets, paths or internals.
Detail: log details server-side; return a stable code and a safe message.
Here: tested by raising an exception containing a fake password.

**9. Sync vs async routes?**
Short: sync routes run in a threadpool; async routes run on the event loop.
Detail: never block inside an async route.
Here: health routes are sync; `/plan` is async because it awaits network calls.

**10. What is OpenAPI and `/docs`?**
Short: a machine-readable API spec plus an interactive UI.
Detail: generated from routes and models, so it can't drift from the code.
Here: tests assert the documented response schemas.

**11. How do you version an API?**
Short: path prefix or headers.
Detail: lets old and new clients coexist during migrations.
Here: `/api/v1`.

**12. Liveness vs readiness endpoints?**
Short: "process alive" vs "ready for traffic".
Detail: liveness failures restart; readiness failures only stop traffic.
Here: `/health` (no external checks), `/health/ready` (configuration present).

**13. How is CORS configured?**
Short: `CORSMiddleware` with explicit origins.
Detail: CORS is a browser rule; server-to-server calls don't need it.
Here: off by default (the UI calls server-side); `CORS_ALLOW_ORIGINS` to enable; `*` refused in prod.

**14. How is rate limiting attached to routes?**
Short: as a route dependency.
Detail: keeps cheap endpoints (health) unaffected.
Here: `dependencies=[Depends(enforce_limits)]` on `/plan` and `/research`.

**15. What is `request.state`?**
Short: per-request storage.
Detail: shared between middleware, dependencies and handlers.
Here: `request.state.request_id`.

**16. What is `app.state`?**
Short: per-application storage.
Detail: good for objects that live as long as the app.
Here: the rate limiter and concurrency limiter.

**17. How do you test FastAPI apps?**
Short: `TestClient` plus dependency overrides.
Detail: runs the full ASGI stack in-process, without a real server.
Here: `tests/api/` and many unit tests.

**18. How does uvicorn shut down gracefully?**
Short: on SIGTERM it stops accepting and waits for in-flight requests.
Detail: bounded by `--timeout-graceful-shutdown`.
Here: 60 s, inside Kubernetes' 75 s grace period.

**19. What does `--proxy-headers` do?**
Short: trusts `X-Forwarded-For/Proto` from allowed proxies.
Detail: the trusted list is `--forwarded-allow-ips` / `FORWARDED_ALLOW_IPS`.
Here: enabled in the Dockerfile; it matters for client IPs behind a load balancer.

**20. Why one worker per container?**
Short: simple resource accounting and per-process state.
Detail: scale by adding replicas, not processes inside one container.
Here: metrics and limiters are per process.

## LLM (25)

**1. What is an LLM?**
Short: a neural network trained to predict the next token.
Detail: instruction tuning makes it follow prompts; generation repeats next-token prediction.
Here: Gemini 2.5 Flash for extraction, planning and repair.

**2. What is a token?**
Short: a chunk of text the model processes, often part of a word.
Detail: context limits and billing are in tokens.
Here: tokens are logged per call when the provider reports them.

**3. What is a context window?**
Short: the maximum tokens a model can read at once.
Detail: overflowing it raises an error or truncates input.
Here: snippet length and entity caps keep prompts bounded; `ContextOverflowError` is mapped to `LLM_ERROR`.

**4. What is temperature?**
Short: randomness in token selection.
Detail: 0 = most likely tokens; higher = more varied.
Here: 0 for extraction, 0.3 for planning.

**5. What is a system prompt?**
Short: standing instructions with higher priority than user content.
Detail: should not contain untrusted text.
Here: role, rules and constraints only; web and user text go in the human message.

**6. What is structured output?**
Short: forcing the model to emit JSON matching a schema.
Detail: constrain generation (schema to the API) and verify (parse + validate).
Here: `response_json_schema` + Pydantic in `StructuredLLM`.

**7. Why validate structured output if the API enforces a schema?**
Short: constraints aren't guarantees.
Detail: providers may support only part of JSON Schema; values can still be wrong.
Here: Pydantic validates every reply; one retry with feedback, then `LLM_INVALID_OUTPUT`.

**8. What is hallucination?**
Short: fluent but false output.
Detail: models optimise plausibility; gaps in context are filled with likely-sounding text.
Here: invented places and prices are the main risk.

**9. How do you reduce hallucination?**
Short: grounding, constraints, verification, honesty fields.
Detail: give evidence, demand citations, check them in code, allow "unknown".
Here: source-verified entities, id-only planning, price quotes, `uncertainty_notes`.

**10. Why not let the LLM do arithmetic?**
Short: unreliable at multi-step math.
Detail: errors are confident and hard to spot.
Here: the budget engine is pure Python.

**11. What is an output retry vs a transport retry?**
Short: re-asking after bad content vs retrying after a failed call.
Detail: both must be bounded.
Here: `LLM_OUTPUT_RETRIES=1` (with error feedback), `LLM_MAX_RETRIES=2` (SDK).

**12. How do you handle LLM timeouts?**
Short: SDK timeout plus an outer hard timeout.
Detail: never let one call hold a request indefinitely.
Here: `asyncio.wait_for`; maps to 504 `LLM_TIMEOUT`.

**13. How do you handle provider rate limits?**
Short: map to 429 and back off.
Detail: surface clearly; don't hammer the provider.
Here: `ModelRateLimitError` → `RATE_LIMITED`; metric outcome `rate_limited`.

**14. Why multiple LLM calls instead of one?**
Short: each call is simpler, checkable and has its own schema.
Detail: verification between steps catches errors early.
Here: extract → ground (code) → plan → validate (code) → repair.

**15. Why different temperatures per call?**
Short: extraction copies facts; planning benefits from slight variety.
Detail: extraction must be repeatable; planning gains from a little variety in arranging days.
Here: 0.0 and 0.3.

**16. What is model-provider abstraction?**
Short: code against an interface, not a vendor SDK.
Detail: switching models becomes a config or factory change.
Here: LangChain `BaseChatModel` + `create_structured_llm`.

**17. How do you estimate LLM cost?**
Short: tokens × current price per token.
Detail: prices change; don't hard-code them silently.
Here: optional `LLM_*_COST_PER_MILLION_USD`; otherwise `estimated_cost_usd: null`.

**18. What determines LLM latency?**
Short: mostly output tokens, plus input size and queueing.
Detail: long JSON outputs are slow.
Here: planning likely dominates; to be measured live.

**19. What is a demo/fake model and why have one?**
Short: a deterministic stand-in with no key.
Detail: runs the same code path for development and tests; must be labelled.
Here: `DemoChatModel`; responses say `data_mode: demo`.

**20. Why log tokens as null instead of 0 when unknown?**
Short: 0 is a false measurement.
Detail: a 0 would make totals and cost estimates look falsely low; null means unknown.
Here: totals stay honest.

**21. What is prompt injection?**
Short: input that tries to override instructions.
Detail: from users or retrieved content.
Here: delimiters, data-not-instructions rules, and code-side verification.

**22. Why is the LLM not trusted for titles any more?**
Short: free text can carry unverified names.
Detail: structure removes the opportunity rather than detecting it after the fact.
Here: titles are generated from verified names (Stage 4 fix).

**23. What is Vertex AI vs the Gemini API?**
Short: GCP's enterprise endpoint vs the AI Studio key-based API.
Detail: Vertex AI supports IAM / Workload Identity (no API key).
Here: future option to remove the Gemini secret.

**24. How would you compare two models?**
Short: run the same evaluation dataset on both and compare scores, latency and cost.
Detail: same dataset, same metrics, plus latency and cost per plan; never compare across datasets.
Here: `evaluation.runner --mode live` with different `LLM_MODEL`.

**25. What is the biggest LLM risk in this app?**
Short: confident wrong facts.
Detail: mitigated by design, not eliminated.
Here: lower-case names and faithful-sounding descriptions remain; Faithfulness evaluation is the backstop.

## LangChain (20)

**1. What is LangChain?**
Short: a library of standard building blocks for LLM apps.
Detail: chat models, prompts, output parsers, tools, retrievers, runnables.
Here: we use only the core pieces.

**2. Which parts are used and why?**
Short: `BaseChatModel`, `ChatPromptTemplate`, provider-neutral exceptions.
Detail: one interface for Gemini, the demo model and test fakes; reviewable prompts; vendor-neutral error mapping.
Here: `app/llm/`, `app/prompts/`.

**3. Which parts were deliberately not used?**
Short: agents, tools, retrievers, chains.
Detail: our steps are fixed and simple; our own code is easier to test and control.
Here: search uses our `SearchProvider`; orchestration uses LangGraph.

**4. What is a ChatPromptTemplate?**
Short: a message template with named variables.
Detail: values are inserted without re-parsing, so braces in data are safe.
Here: `RESEARCH_PROMPT`, `PLANNER_PROMPT`, `REPAIR_PROMPT`.

**5. What is a Runnable?**
Short: LangChain's common interface: `invoke`, `ainvoke`, `batch`, `stream`.
Detail: models, prompts and chains all implement it.
Here: we call `ainvoke` on the (bound) chat model.

**6. What does `.bind()` do?**
Short: pre-sets call arguments.
Detail: returns a new runnable with fixed kwargs.
Here: `response_mime_type` and `response_json_schema` for Gemini.

**7. Why not `with_structured_output()`?**
Short: we wanted control over parsing, retries and errors.
Detail: in this library version it binds the same parameters but hides the parse step.
Here: `StructuredLLM.generate` does parse → validate → feedback retry → domain error.

**8. What is `ChatGoogleGenerativeAI`?**
Short: LangChain's Gemini chat model.
Detail: converts messages and errors; supports timeouts and retries.
Here: built in `create_structured_llm`.

**9. What are AIMessage / HumanMessage / SystemMessage?**
Short: typed chat messages with roles.
Detail: the system message becomes Gemini's `system_instruction`.
Here: prompts produce `[system, human]`; repair appends feedback messages.

**10. What is `usage_metadata`?**
Short: token counts on the AIMessage.
Detail: may be missing for some providers.
Here: logged per call; summed per request.

**11. How do you fake a model in tests?**
Short: subclass `BaseChatModel` and return scripted messages.
Detail: no network, deterministic.
Here: `ScriptedChatModel`, `SlowChatModel`, `DemoChatModel`.

**12. How are LangChain errors mapped?**
Short: catch `ModelRateLimitError`, `ModelAuthenticationError`, `ModelTimeoutError`…
Detail: these are provider-neutral classes in `langchain_core.exceptions`.
Here: mapped to `RATE_LIMITED`, `LLM_AUTH_ERROR`, `LLM_TIMEOUT`.

**13. What are output parsers?**
Short: classes that turn text into objects.
Detail: e.g. a Pydantic output parser.
Here: replaced by our own parse + validate for better error control.

**14. What is the LangChain vs LangGraph split?**
Short: components vs orchestration.
Detail: LangChain gives building blocks (models, prompts); LangGraph composes steps into a stateful workflow.
Here: LangChain for model and prompts; LangGraph for the workflow.

**15. How would you switch to another provider?**
Short: add a branch in the factory returning another chat model.
Detail: prompts, parsing, grounding and graph stay unchanged.
Here: `app/llm/factory.py`.

**16. What is LangSmith and is it used?**
Short: LangChain's tracing platform; not used.
Detail: we chose JSON logs to avoid an external dependency.
Here: possible future tracing option.

**17. Why are braces in web content safe in prompts?**
Short: template variables are substituted once; inserted values aren't re-templated.
Detail: values are inserted once; they are not parsed again as template syntax.
Here: tested with `{destination}` inside a source.

**18. How do you keep prompts maintainable?**
Short: separate modules, version constants, tests on the rendered text.
Detail: prompt text as data in its own module, with a version constant and rendering tests.
Here: `PROMPT_VERSION`, `PLANNER_PROMPT_VERSION`; tests check sections and rules.

**19. What does LangChain add to latency?**
Short: negligible compared with network calls.
Detail: a few function calls and object conversions per request, microseconds to milliseconds.
Here: total non-network overhead ~30 ms per plan (measured, demo).

**20. Biggest risk of using LangChain?**
Short: API churn across versions.
Detail: pin versions; use thin, well-tested wrappers.
Here: exact pins; our `StructuredLLM` wrapper isolates the rest of the code.

## LangGraph (20)

**1. What is LangGraph?**
Short: a library for building workflows as graphs of steps over a shared state.
Detail: supports parallel branches, conditional edges, loops and checkpoints.
Here: research and planning graphs in `app/graph/`.

**2. Why LangGraph instead of plain functions?**
Short: parallel fan-out/fan-in, a typed state and bounded loops, built in.
Detail: hand-written orchestration gets messy as steps grow.
Here: 5 parallel searches; validate ⇄ repair loop.

**3. What is the state?**
Short: a TypedDict passed between nodes.
Detail: nodes return partial updates that LangGraph merges.
Here: `ResearchState`, `PlannerState`.

**4. What is a reducer?**
Short: how concurrent writes to one key are combined.
Detail: without one, parallel writes conflict.
Here: `Annotated[list, operator.add]` for `category_results`, `warnings`, `llm_usage`.

**5. How does fan-out/fan-in work?**
Short: several edges from one node; one edge from a list of nodes.
Detail: the target waits for all sources.
Here: `prepare_queries` → 5 search nodes → `aggregate_research`.

**6. What is a conditional edge?**
Short: a function choosing the next node from the state.
Detail: the router function reads the state and returns the next node's name.
Here: `route_after_validation` → repair, give up, or assemble.

**7. How is the loop bounded?**
Short: a counter in the state compared with a setting.
Detail: guarantees termination, cost and latency limits.
Here: `repair_attempts < MAX_REPAIR_ATTEMPTS`.

**8. How do errors propagate?**
Short: an exception in a node stops the graph and reaches the caller.
Detail: no special handling is needed; the graph stops at the failing node.
Here: domain errors reach FastAPI's handlers.

**9. How do you reuse nodes across graphs?**
Short: a function that adds nodes to any graph and returns the last node's name.
Detail: avoids duplicating node definitions between graphs.
Here: `add_research_nodes()` serves both `/research` and `/plan`.

**10. How are dependencies injected into nodes?**
Short: closures over provider objects.
Detail: tests pass fakes; no globals.
Here: `build_planning_graph(provider, research_llm, planner_llm, settings)`.

**11. Workflow or agent?**
Short: a workflow with one agentic loop.
Detail: fixed steps for predictability; self-correction only where feedback exists.
Here: no LLM decides whether to search.

**12. When would you use a real agent?**
Short: open-ended tasks with variable steps.
Detail: when the next step genuinely depends on intermediate results and can't be fixed in advance.
Here: e.g. "find a cheaper hotel near day 2"; not built.

**13. Does the graph keep state between requests?**
Short: no; each request starts fresh.
Detail: no checkpointer is configured.
Here: stateless service, which is why horizontal scaling is easy.

**14. How do you test a graph?**
Short: run it with fake providers and assert on the final state or response.
Detail: the real graph runs; only external services are replaced by fakes.
Here: `tests/integration/`.

**15. How does async work inside LangGraph?**
Short: async nodes run on the event loop; parallel branches run concurrently.
Detail: `ainvoke` drives the graph; branches with no dependency between them run concurrently.
Here: search and LLM nodes are async.

**16. How do ContextVars behave in nodes?**
Short: nodes see a copy of the request context.
Detail: mutable objects in it are shared.
Here: `RequestStats` counters are updated from nodes.

**17. Where would you add tracing?**
Short: around each node and external call.
Detail: spans give per-step timing and parent/child structure across the request.
Here: future OpenTelemetry spans per node.

**18. What happens if one search fails?**
Short: the node records the error; aggregation continues.
Detail: all failing → raise the real cause; nothing usable → `NO_RESEARCH_RESULTS`.
Here: `partial` status with a warning.

**19. Why compile the graph per request?**
Short: dependencies differ per request (settings, injected fakes).
Detail: compiling is cheap compared with network calls.
Here: built in `TravelPlanner.run`.

**20. What is a checkpointer and why not used?**
Short: persists state between steps for resumption or human-in-the-loop.
Detail: unnecessary for short, stateless requests.
Here: future option for long-running or resumable plans.

## RAG and grounding (20)

**1. What is RAG?**
Short: retrieval-augmented generation: retrieve relevant text, then generate using it.
Detail: grounds answers in current or private data instead of model memory.
Here: retrieval is live web search; generation is extraction and planning.

**2. Is this project RAG without a vector database?**
Short: yes. Retrieval doesn't have to be vector search.
Detail: vector DBs suit large private corpora; we need fresh public facts.
Here: Tavily replaces a vector store.

**3. When would you add a vector database?**
Short: for a stable private corpus or semantic caching.
Detail: e.g. curated guides, or reusing past research for similar requests.
Here: not added because nothing justified it.

**4. What is grounding?**
Short: tying every output claim to evidence.
Detail: by prompt instructions and, more reliably, by code checks.
Here: names and prices must appear in cited sources; planning uses verified ids only.

**5. How do you make citations checkable?**
Short: number sources and require ids, not URLs or prose.
Detail: ids are easy to validate in code.
Here: `S1..Sn`; entities carry `source_id`.

**6. How do you verify an extracted entity?**
Short: the cited source exists and its text contains the entity name.
Detail: case-, accent- and punctuation-insensitive, whole-word matching.
Here: `research/grounding.py` → `NAME_NOT_IN_SOURCE`.

**7. How do you verify a price?**
Short: the quote must be in the source and contain the amount.
Detail: otherwise drop the price, never estimate it.
Here: `verify_price` → `QUOTE_NOT_IN_SOURCE` / `AMOUNT_NOT_IN_QUOTE`.

**8. What is the retrieval quality problem?**
Short: irrelevant or duplicate results waste context and mislead.
Detail: filter, deduplicate and truncate before generation.
Here: the normalizer drops non-http, short, irrelevant and duplicate results.

**9. How do you filter irrelevant results cheaply?**
Short: require the destination as a whole word.
Detail: crude but effective; "goal" doesn't match "Goa".
Here: `mentions_destination`.

**10. What is context stuffing?**
Short: putting too much into the prompt.
Detail: raises cost and latency and can reduce accuracy.
Here: `SEARCH_MAX_RESULTS`, `SEARCH_MAX_CONTENT_CHARS`, `MAX_ENTITIES_PER_CATEGORY`.

**11. How do you defend against injected instructions in retrieved text?**
Short: delimit, label as data, and verify outputs in code.
Detail: prompts alone can't guarantee it.
Here: `<source>` blocks with look-alike tags stripped; grounding still applies.

**12. What is faithfulness vs answer relevance?**
Short: supported by context vs addresses the question.
Detail: you need both.
Here: Faithfulness (judge) + preference metrics.

**13. What happens when retrieval returns nothing?**
Short: stop. Don't let the model answer from memory.
Detail: return a clear error instead.
Here: `NO_RESEARCH_RESULTS` before any LLM call.

**14. What is partial retrieval failure?**
Short: some sources fail; continue with a warning.
Detail: degrade gracefully and tell the user.
Here: `status: partial` plus a per-category summary.

**15. How is grounding enforced in the second LLM call?**
Short: ids only, plus a closed list of generic kinds.
Detail: titles and prices are generated by code.
Here: `ItineraryDraft` has no title or price fields.

**16. What does the named-place check catch, and what does it miss?**
Short: capitalised multi-word names not in verified research; misses lower-case names.
Detail: a secondary, heuristic layer behind the structural one.
Here: `UNSUPPORTED_NAMED_PLACE`.

**17. Why only "verified" evidence for names?**
Short: a passing mention in a raw source isn't verification.
Detail: only grounded entities count.
Here: `research_evidence()` excludes raw hit text.

**18. How would you measure grounding quality?**
Short: share of outputs traceable to evidence, plus a faithfulness score.
Detail: deterministic ratios online, judges offline.
Here: `grounded_activity_ratio`, `entity_grounding`, Faithfulness.

**19. Why keep sources in the response?**
Short: users can check claims themselves.
Detail: transparency is part of trust.
Here: `sources` with URLs; shown in the UI.

**20. Biggest residual grounding risk?**
Short: a malicious or wrong source that genuinely mentions a place.
Detail: verification proves "mentioned", not "true".
Here: show sources; multi-source corroboration is a future improvement.

## Prompt engineering (20)

**1. What makes a good prompt?**
Short: a clear role, context, rules, constraints and an output format.
Detail: specific, testable instructions beat vague ones.
Here: both prompts are structured ROLE / RULES / CONSTRAINTS / CONTEXT / DATA / TASK.

**2. Why separate system and human messages?**
Short: stable rules vs per-request data.
Detail: untrusted data never goes into the system message.
Here: tested: the system prompt never contains web or user text.

**3. Why put prompts in separate modules?**
Short: reviewable, testable, versioned.
Detail: the code that calls the model stays generic.
Here: `app/prompts/`.

**4. Why version prompts?**
Short: to know which prompt produced which result.
Detail: evaluation results only compare within a version.
Here: `research-extraction-v1`, `itinerary-planner-v2` recorded in eval reports.

**5. How do you write rules the model follows?**
Short: short, numbered, unambiguous, with examples of edge cases.
Detail: name common failure modes explicitly.
Here: "Do not invent places, prices, opening hours…".

**6. Why tell the model the limits the code enforces?**
Short: fewer repair rounds.
Detail: same constants in the prompt and in the validator.
Here: pace caps come from `planning/rules.py` in both.

**7. How do you constrain output format?**
Short: a JSON schema plus a format reminder.
Detail: schema-bound generation where supported, validation always.
Here: `response_json_schema` + Pydantic.

**8. What is few-shot prompting and why not used here?**
Short: including examples in the prompt.
Detail: costs tokens and can bias outputs; the schema and rules sufficed.
Here: possible improvement if live evaluation shows format issues.

**9. How do you give the model an "I don't know" option?**
Short: an explicit field for uncertainty.
Detail: reduces pressure to invent.
Here: `uncertainty_notes`; `price: null`.

**10. How do you handle user free text safely?**
Short: delimit it, cap its length, and state it can't change the rules.
Detail: neutralise characters that could close the delimiter.
Here: `<traveller_notes>` with `<`/`>` replaced.

**11. What is a repair prompt?**
Short: a prompt with the previous output plus the exact errors to fix.
Detail: precise feedback beats "try again".
Here: `REPAIR_PROMPT` with `[CODE] day N: message` lines.

**12. Why ask for sentence case?**
Short: it reduces false positives in the capitalised-name check.
Detail: prompt and validator are designed together.
Here: planner rule 2.

**13. How do you test prompts without an LLM?**
Short: assert on the rendered text.
Detail: check rules, delimiters and the absence of injected text.
Here: `test_research_prompt.py`, `test_planner_prompt.py`.

**14. How do you evaluate prompt changes?**
Short: run the evaluation dataset before and after.
Detail: compare aggregate scores, failure codes, latency and cost between versions.
Here: `evaluation.runner --mode live` (to do).

**15. What's prompt sensitivity?**
Short: small wording changes alter outputs.
Detail: rely on code checks, not perfect wording.
Here: grounding and validation catch what the prompt misses.

**16. How do you show prices without letting the model output them?**
Short: show them in the input, omit them from the output schema.
Detail: input fields inform choices; the output schema decides what can be said.
Here: ALLOWED PLACES shows quotes; the draft has no price fields.

**17. How long should prompts be?**
Short: as short as possible while unambiguous.
Detail: every token costs money and latency.
Here: data is trimmed (snippet caps); rules are concise.

**18. What's the role of temperature in prompt design?**
Short: lower for extraction, slightly higher for creative arrangement.
Detail: temperature is part of the prompt contract: what variability is acceptable.
Here: 0 and 0.3.

**19. How do you stop the model adding fields?**
Short: `extra="forbid"` in the schema.
Detail: invented fields become validation errors.
Here: all schemas inherit `StrictModel`.

**20. What would you change after the first live run?**
Short: whatever the failure metrics point to.
Detail: e.g. if `UNSUPPORTED_NAMED_PLACE` dominates, strengthen rule 2 or add an example.
Here: `validation_failures_total{code}`.

## LLM evaluation (20)

**1. What is LLM evaluation?**
Short: measuring the quality of model outputs, not the correctness of code.
Detail: run realistic inputs through the real system and score outputs on defined criteria with thresholds.
Here: scoring itineraries for grounding, relevance, completeness, faithfulness and constraints.

**2. Why aren't unit tests enough?**
Short: unit tests use fake models; real outputs vary with the model, prompt and data.
Detail: tests prove the code handles outputs correctly, not that the outputs are good.
Here: 260+ tests can pass while Gemini writes an incoherent plan.

**3. Deterministic tests vs integration tests vs evaluation?**
Short: one function with exact asserts / many components with fakes / the real system with scores.
Detail: the first two are cheap, run every commit and are exact; evaluation costs money, is variable, and runs on releases or prompt changes.
Here: `tests/unit`, `tests/integration`, `evaluation/`.

**4. What is grounding?**
Short: the answer uses only provided, verified information.
Detail: in RAG systems, outputs should be traceable to retrieved evidence.
Here: every activity is a verified entity id (traceable to a source URL) or an explicit generic kind.

**5. Faithfulness vs grounding?**
Short: grounding is about which entities are used; faithfulness about whether claims are supported.
Detail: a plan can use only real places (grounded) yet describe them wrongly (unfaithful).
Here: code checks ids and names; DeepEval Faithfulness checks descriptive claims against the research.

**6. What is relevance?**
Short: whether the answer addresses what was asked.
Detail: for structured requests, coverage of each stated preference.
Here: interests, style, diet, pace: `preference_match` (coarse, code) + `preference_alignment` (judge).

**7. What is completeness?**
Short: everything requested is present.
Detail: a missing day is a failure even if the other days are excellent.
Here: days 1..N, dates, all budget categories, sources.

**8. What is consistency?**
Short: no contradictions, internally or with the numbers.
Detail: LLMs can state totals that disagree with their own items.
Here: budget computed in code and checked to sum exactly; the coherence judge looks for narrative contradictions.

**9. How do you measure hallucination?**
Short: compare outputs with evidence and count unsupported entities or claims.
Detail: combine exact checks (names, ids) with judge checks (claims).
Here: `unsupported_places`, `entity_grounding`, Faithfulness.

**10. What is LLM-as-a-judge?**
Short: an LLM scores another LLM's output against a rubric.
Detail: useful for subjective criteria; typically uses evaluation steps and a fixed scale.
Here: Gemini judges coherence, preference alignment and usefulness.

**11. Limitations of LLM judges?**
Short: bias, prompt sensitivity, non-determinism, cost.
Detail: judges favour long and confident text, and they shift with wording.
Here: documented in `docs/19`; scores treated as signals, never as ground truth.

**12. What is self-preference bias?**
Short: a model rating outputs like its own higher.
Detail: measurable when the same family both generates and judges.
Here: `EVAL_JUDGE_MODEL` lets a different model judge.

**13. How do you reduce judge variance?**
Short: temperature 0, explicit steps, averaging over many cases.
Detail: compare aggregates across runs, not single scores.
Here: all three are applied in `metrics/judge.py`.

**14. What makes a good evaluation dataset?**
Short: realistic, diverse, stable inputs including edge cases.
Detail: it should reflect real usage and known failure modes.
Here: 5 cities, 5 travel styles, hostel→luxury, dietary needs, a 1-day trip.

**15. Why not store expected itineraries?**
Short: there are many valid answers, and web facts change.
Detail: property-based checks generalise; exact references go stale.
Here: we store inputs and expected behaviour; metrics check properties.

**16. Offline vs online evaluation?**
Short: offline runs a dataset; online watches signals on real traffic.
Detail: you need both, to catch regressions before release and drift after it.
Here: the evaluation runner (offline) + `QualityReport` and metrics on every request (online).

**17. How do you evaluate a prompt change?**
Short: run the same dataset before and after, and compare.
Detail: change one thing at a time; record versions.
Here: reports include `planner_prompt: itinerary-planner-v2`.

**18. How do you set thresholds?**
Short: start with engineering judgement, then calibrate with data and human labels.
Detail: thresholds encode product decisions and should be revisited.
Here: INITIAL ENGINEERING THRESHOLDS, explicitly unvalidated.

**19. What is regression evaluation?**
Short: checking that quality doesn't drop after changes.
Detail: automated runs gate releases on aggregate scores.
Here: `python -m evaluation.runner --mode live` per release via the manual `eval-live.yml` workflow.

**20. When do you need humans?**
Short: to calibrate judges and thresholds, and for subjective quality.
Detail: human ratings on a sample show whether judge scores track what users care about.
Here: rate a sample of live itineraries and compare them with judge scores.

## DeepEval (20)

**1. What is DeepEval?**
Short: an open-source framework for testing LLM applications with metrics and thresholds.
Detail: provides `LLMTestCase`, built-in LLM-judge metrics (Faithfulness, G-Eval, Answer Relevancy…), a `BaseMetric` for custom metrics, and pytest integration.
Here: `evaluation/` uses it for 7 code metrics and 4 judge metrics.

**2. What is an `LLMTestCase`?**
Short: one evaluation example: input, actual output, optional expected output, retrieval context, metadata.
Detail: metrics read the fields they need; judge metrics use text fields, custom metrics can use metadata.
Here: `testcase_builder.py` renders the request (input), the itinerary (actual_output) and the verified research (retrieval_context), and stores full JSON in metadata.

**3. What does a DeepEval metric return?**
Short: a score (0–1), a reason, and success = score ≥ threshold.
Detail: `measure()` sets `score`, `reason`, `success`; `is_successful()` reports it; `a_measure` is the async version.
Here: every metric in the report has `score`, `threshold`, `passed`, `explanation`.

**4. How do you write a custom metric?**
Short: subclass `BaseMetric`, implement `measure`, `a_measure`, `is_successful`, and a `__name__`.
Detail: put deterministic logic in `measure`; no LLM call required.
Here: `_DeterministicMetric` base in `metrics/deterministic.py`; e.g. `BudgetConstraintMetric`.

**5. What is G-Eval?**
Short: an LLM-judge metric that scores against your own criteria or evaluation steps.
Detail: the judge follows explicit steps and produces a probability-weighted score, which makes it more consistent than a single free-form rating.
Here: `itinerary_coherence`, `preference_alignment`, `usefulness`.

**6. What is the Faithfulness metric?**
Short: checks whether claims in the output are supported by the retrieval context.
Detail: extracts claims from the output and truths from the context, then asks the judge whether each claim contradicts or is unsupported.
Here: compares itinerary text with the verified entity descriptions (the textual complement to our name check).

**7. What is `retrieval_context`?**
Short: the evidence the answer was supposed to use.
Detail: in RAG, the retrieved documents; faithfulness/contextual metrics read it.
Here: verified entity facts + destination overview; for research evaluation, the raw search snippets.

**8. `assert_test` vs `evaluate()`?**
Short: `assert_test` fails a pytest test if any metric fails; `evaluate` runs many cases and returns results.
Detail: `deepeval test run file.py` wraps pytest with DeepEval reporting.
Here: `evaluation/test_itinerary.py` uses `assert_test`; the runner calls `metric.measure` directly to write our own JSON report.

**9. Why did you write your own runner instead of only `deepeval test run`?**
Short: to control the report format and keep everything local.
Detail: our report includes mode labels, prompt versions, judge status and threshold status. Those are needed to interpret scores honestly.
Here: `evaluation/runner.py` → `results/eval-<time>-<mode>.json`.

**10. How do you choose the judge model?**
Short: a strong model, ideally different from the one being judged.
Detail: same-model judging risks self-preference bias.
Here: `EVAL_JUDGE_MODEL`; defaults to `LLM_MODEL` with the bias documented.

**11. Does DeepEval send data anywhere?**
Short: it can send telemetry and can upload to Confident AI if you log in.
Detail: telemetry can be disabled with `DEEPEVAL_TELEMETRY_OPT_OUT=YES`.
Here: opted out in `evaluation/__init__.py` and `tests/conftest.py`; no Confident AI login; reports stay local.

**12. Why is DeepEval not in the API image?**
Short: it's offline tooling with heavy dependencies.
Detail: smaller images, smaller attack surface.
Here: `requirements-eval.txt` only.

**13. How do thresholds work?**
Short: a metric passes if score ≥ threshold.
Detail: thresholds encode "good enough"; they must be calibrated.
Here: `evaluation/config.py`, labelled INITIAL ENGINEERING THRESHOLDS, overridable by env.

**14. Why are deterministic thresholds 1.0?**
Short: rules either hold or they don't.
Detail: "one invented place out of ten" is not 90% acceptable.
Here: grounding, completeness, budget, constraints = 1.0; preference match = 0.6 because it's a coarse proxy.

**15. Why did a demo evaluation case fail?**
Short: the metric correctly saw that demo data had no adventure/nature places.
Detail: a failing metric on bad output is the system working.
Here: `bengaluru_solo_adventure`: "not covered ['adventure', 'nature']".

**16. What is `strict_mode`?**
Short: forces a binary score (1 or 0) using threshold 1.
Detail: useful for hard gates.
Here: not used; our code metrics are already exact.

**17. How do you keep evaluation from slowing normal tests?**
Short: keep it in a separate folder and command.
Detail: DeepEval registers a pytest plugin, so we disable it for `tests/`.
Here: `addopts = "-p no:deepeval"` in `pyproject.toml`; `evaluation/pytest.ini` keeps it for evaluation.

**18. Can DeepEval evaluate without an LLM?**
Short: yes, with custom metrics.
Detail: built-in judge metrics need a model; `BaseMetric` subclasses don't.
Here: the demo evaluation runs only code metrics.

**19. What does the judge cost?**
Short: several LLM calls per case per metric.
Detail: Faithfulness extracts claims and truths and verifies them (multiple calls); G-Eval at least one each.
Here: opt-in `--judge`, intended for releases.

**20. How would you track evaluation over time?**
Short: store reports per commit/prompt version and compare aggregates.
Detail: trend mean scores and pass rates; investigate drops.
Here: reports include `git_sha`, prompt versions, model; CI integration is Stage 5.

## Docker (25)

**1. What is Docker?**
Short: a tool to package and run applications in containers.
Detail: images built from Dockerfiles, run as isolated processes.
Here: API and Streamlit images.

**2. Image vs container?**
Short: the template vs a running instance.
Detail: many containers can run from one image.
Here: `ai-travel-planner-api:local` → the `api` container.

**3. What is a layer?**
Short: the cached filesystem change from one instruction.
Detail: unchanged layers are reused.
Here: requirements are copied before code, so dependency layers survive code edits.

**4. What is a multi-stage build?**
Short: build in one stage, copy only results to a clean final stage.
Detail: smaller images, no build tools at runtime.
Here: venv built in `builder`, copied to `runtime`.

**5. Why a slim base image?**
Short: smaller size and attack surface.
Detail: Alpine can break Python wheels (musl); slim Debian is a safe default.
Here: `python:3.12.14-slim-trixie`.

**6. Why run as non-root?**
Short: limits damage if the app is compromised.
Detail: root in a container is closer to root on the host than people assume.
Here: `USER app` (uid 10001); a test enforces it.

**7. How do you keep secrets out of images?**
Short: never COPY them; pass them at runtime.
Detail: anything in a layer can be extracted, even if a later layer deletes it.
Here: `.dockerignore` excludes `.env`; keys come from `env_file` / `--env-file` / Kubernetes Secrets.

**8. What does `.dockerignore` do?**
Short: excludes files from the build context.
Detail: smaller, faster, safer builds.
Here: `.env*`, `.git`, `.venv`, tests, docs, evaluation.

**9. `CMD` exec form vs shell form?**
Short: exec form runs the process directly as PID 1.
Detail: shell form wraps it in `/bin/sh`, which may not forward SIGTERM.
Here: `CMD ["uvicorn", ...]`.

**10. What is HEALTHCHECK?**
Short: a command Docker runs to mark a container healthy or unhealthy.
Detail: compose `depends_on: condition: service_healthy` uses it.
Here: Python `urllib` to `/api/v1/health` (no curl in slim).

**11. Why not call Gemini in the health check?**
Short: cost, rate limits, and coupling to a third party's uptime.
Detail: restarting our container doesn't fix their outage.
Here: liveness checks nothing external; readiness checks configuration only.

**12. `EXPOSE` vs publishing a port?**
Short: EXPOSE documents; `-p`/`ports` actually publishes.
Detail: containers on the same network can reach each other without publishing.
Here: EXPOSE 8000; compose publishes on 127.0.0.1 only.

**13. `ENV` vs `ARG`?**
Short: runtime env var vs build-time variable.
Detail: ARGs are visible in image history; never put secrets in them.
Here: `ARG GIT_SHA` → `ENV GIT_SHA`.

**14. `PYTHONUNBUFFERED=1`, why?**
Short: logs appear immediately.
Detail: buffered stdout can lose or delay lines on crashes.
Here: JSON logs reach `docker logs` in real time.

**15. How many workers per container?**
Short: one, scaled by more containers.
Detail: simpler resource limits; per-process metrics stay coherent.
Here: single uvicorn worker.

**16. How do you pin dependencies reproducibly?**
Short: exact versions in requirements and pinned base images.
Detail: `:latest` changes under you.
Here: `==` pins; no `:latest` (tested).

**17. How do you debug a container?**
Short: `docker logs`, `docker exec -it <c> sh`, `docker inspect`.
Detail: health status in `docker ps`.
Here: JSON logs; `/api/v1/version` shows the git sha.

**18. How would you scan an image for vulnerabilities?**
Short: tools such as Trivy, Grype, or a registry scanner.
Detail: fail builds on critical CVEs.
Here: Trivy runs in CI (`ci.yml`, images job); not run locally (no Docker).

**19. Why are the API and UI separate images?**
Short: independent scaling, deploys and dependencies.
Detail: the UI needs no API keys or LangChain.
Here: `Dockerfile` and `frontend/Dockerfile`.

**20. What did you verify about Docker in this project?**
Short: configuration via static tests; builds NOT run (Docker unavailable).
Detail: honest status matters more than claimed success.
Here: `tests/unit/test_container_config.py`; the run procedure is in `docs/22`.

**21. Why a numeric `USER` in the Dockerfile?**
Short: Kubernetes `runAsNonRoot` can only verify numeric ids.
Detail: a name like `app` can't be checked against the image without the passwd file.
Here: `USER 10001:10001` (hadolint DL3066 fixed).

**22. Why set WORKDIR in the builder stage?**
Short: predictable relative paths.
Detail: COPY to a relative path without WORKDIR depends on defaults.
Here: `WORKDIR /build` (hadolint DL3045 fixed).

**23. What does `--timeout-graceful-shutdown` add?**
Short: in-flight plans can finish on SIGTERM.
Detail: must be shorter than the orchestrator's grace period.
Here: 60 s vs Kubernetes 75 s (tested).

**24. How big are the images, and how do you keep them small?**
Short: not measured (no Docker); slim base, multi-stage, runtime-only dependencies.
Detail: measure with `docker images` on the first build.
Here: the API image excludes Streamlit, DeepEval and pytest.

**25. How does the container behave with a read-only root filesystem?**
Short: it must write only to mounted volumes.
Detail: Python bytecode writing is disabled; temp files go to `/tmp` (emptyDir).
Here: configured in Kubernetes; not yet run (NOT VERIFIED).

## Docker Compose (15)

**1. What is Docker Compose?**
Short: a YAML file plus CLI to run multi-container apps.
Detail: describes services, networks, volumes and environment in one file; `docker compose up` creates them in dependency order.
Here: api, frontend, and optional ELK.

**2. How do services find each other?**
Short: by service name on the project network (built-in DNS).
Detail: Compose creates a bridge network per project and registers each service name in its internal DNS.
Here: `http://api:8000`, `http://elasticsearch:9200`.

**3. What does `depends_on: condition: service_healthy` do?**
Short: waits until the dependency's healthcheck passes.
Detail: without a condition, `depends_on` only orders container *start*, not readiness.
Here: frontend waits for api; Logstash and Kibana wait for Elasticsearch.

**4. What are profiles?**
Short: optional groups of services enabled with `--profile`.
Detail: services with a profile start only when that profile is requested; default services always start.
Here: `elk`, because it needs ~3 GB RAM.

**5. Named volume vs bind mount?**
Short: Docker-managed storage vs a host path.
Detail: named volumes are portable and survive container removal; bind mounts are for files you edit on the host.
Here: `app-logs`/`es-data` are named; the Logstash pipeline is a read-only bind mount.

**6. How do two containers share logs?**
Short: mount the same named volume.
Detail: the producer mounts read-write and the consumer read-only, so the consumer can't corrupt the data.
Here: api writes `/var/log/app`, Logstash mounts it read-only.

**7. How are secrets passed in compose?**
Short: `env_file` at runtime, never in the YAML.
Detail: values in the YAML would be committed to Git; `env_file` reads a git-ignored file at start-up.
Here: `env_file: [{path: .env, required: false}]`; a test forbids `*_API_KEY` keys in `environment:`.

**8. Why bind ports to 127.0.0.1?**
Short: so services aren't exposed to the network.
Detail: `8000:8000` binds on 0.0.0.0, exposing the service to anyone on the network.
Here: all published ports, which matters because local ES/Kibana have no authentication.

**9. `down` vs `down -v`?**
Short: remove containers vs also delete volumes.
Detail: named volumes persist across `down` so data survives restarts.
Here: `-v` deletes indexed logs and the Logstash position.

**10. What is a one-shot service?**
Short: a container that runs a task and exits.
Detail: combine with `restart: "no"` and dependency conditions so it runs once, at the right time.
Here: `elk-setup` creates the Kibana data view and saved searches.

**11. `restart: unless-stopped`?**
Short: restart after crashes or reboots unless you stopped it.
Detail: other options are `no`, `always` and `on-failure`.
Here: api and frontend.

**12. Build args in compose?**
Short: `build.args` passes ARG values.
Detail: args are build-time only and visible in image history, so never pass secrets this way.
Here: `GIT_SHA: ${GIT_SHA:-unknown}`.

**13. How do you check a compose file without running it?**
Short: `docker compose config`.
Detail: it validates and prints the fully resolved configuration (interpolated variables, merged files).
Here: not available on the build machine; static YAML tests instead.

**14. Compose vs Kubernetes?**
Short: single-host development vs a multi-node orchestrator.
Detail: Kubernetes adds scheduling across nodes, self-healing, rolling updates and declarative scaling.
Here: compose locally; Kubernetes manifests for kind and GKE (docs/23).

**15. Why is the frontend's only setting `API_BASE_URL`?**
Short: least privilege: the UI needs no keys.
Detail: each component gets only the configuration it needs.
Here: a compromised UI container can't leak Gemini or Tavily keys.

## Kubernetes (30)

**1. What is Kubernetes?**
Short: a system that runs and manages containers across machines.
Detail: you declare desired state; controllers keep reality matching it.
Here: runs the API and UI images.

**2. What is a Pod?**
Short: the smallest deployable unit: one or more containers sharing a network namespace.
Detail: ephemeral, and replaced rather than repaired.
Here: one container per pod.

**3. What is a Deployment?**
Short: manages replicated pods and rolling updates.
Detail: creates ReplicaSets; supports rollback.
Here: `api` (2), `frontend` (1).

**4. What is a ReplicaSet?**
Short: keeps N identical pods running.
Detail: managed by Deployments; `rollout undo` switches back to the previous one.
Here: used by the rollback in `deploy.yml`.

**5. What is a Service?**
Short: a stable virtual IP and DNS name for a set of pods.
Detail: selects pods by labels; load-balances between ready pods.
Here: `api.travel-planner.svc.cluster.local:8000`.

**6. ClusterIP vs NodePort vs LoadBalancer?**
Short: internal only vs every node's port vs a cloud load balancer.
Detail: expose as little as possible.
Here: both Services are ClusterIP; the Ingress exposes the UI.

**7. What is an Ingress?**
Short: HTTP(S) routing from outside into Services.
Detail: implemented by a controller (GKE: Google Cloud load balancer).
Here: UI only; the API stays internal.

**8. ConfigMap vs Secret?**
Short: non-sensitive config vs sensitive values.
Detail: Secrets are base64-encoded (not encrypted) with stricter access; external managers are better.
Here: `api-config`; secrets via `kubectl create secret` (local) or Secret Manager (GKE).

**9. How do pods get configuration?**
Short: env vars (`envFrom`) or mounted files.
Detail: env vars suit small values; files suit secrets and rotation.
Here: ConfigMap env; Secret Manager files via `SECRETS_DIR`.

**10. Liveness vs readiness vs startup probes?**
Short: restart if dead / route traffic only if ready / wait for startup.
Detail: separate concerns to avoid restart loops.
Here: `/health`, `/health/ready`, `/health` with 30×2 s.

**11. Why must liveness not call external services?**
Short: an outage elsewhere would restart healthy pods.
Detail: restarts can't fix someone else's outage.
Here: `/health` checks nothing external.

**12. What are resource requests and limits?**
Short: requests reserve capacity; limits cap usage.
Detail: CPU over limit is throttled; memory over limit is OOM-killed.
Here: API 200m/256Mi requested, 1 CPU / 512Mi limit (based on 116 MiB measured).

**13. What is a QoS class?**
Short: Guaranteed / Burstable / BestEffort, from requests and limits.
Detail: affects eviction order under pressure.
Here: Burstable (requests < limits).

**14. What is an HPA?**
Short: autoscales replicas based on metrics.
Detail: needs the metrics API; target relative to requests.
Here: API 2–6 at 60% CPU.

**15. Why is CPU a weak scaling signal here?**
Short: the API mostly waits on network calls.
Detail: load can rise without CPU rising.
Here: better: in-flight requests or busy-rejection rate via custom metrics.

**16. What is a PodDisruptionBudget?**
Short: limits voluntary evictions.
Detail: protects availability during node maintenance.
Here: `minAvailable: 1` for the API.

**17. What is a rolling update?**
Short: replace pods gradually.
Detail: `maxSurge` and `maxUnavailable` control the pace.
Here: `maxUnavailable: 0, maxSurge: 1`.

**18. How does graceful shutdown work in Kubernetes?**
Short: preStop → SIGTERM → grace period → SIGKILL.
Detail: endpoints are removed while the app finishes in-flight work.
Here: `sleep 5` + uvicorn 60 s < 75 s grace.

**19. What is a securityContext?**
Short: pod and container security settings.
Detail: pod-level settings apply to all containers; container-level ones override.
Here: non-root uid 10001, read-only root filesystem, drop ALL capabilities, no privilege escalation, seccomp RuntimeDefault.

**20. Why a read-only root filesystem?**
Short: an attacker can't modify the container's files.
Detail: provide explicit writable volumes where needed.
Here: emptyDir for `/tmp` (and `/home/app` for Streamlit).

**21. What is a NetworkPolicy?**
Short: firewall rules for pod traffic.
Detail: enforced only by supporting CNIs.
Here: default deny; UI→API:8000; API→443 except the metadata server; DNS.

**22. What is a ServiceAccount?**
Short: an identity for pods.
Detail: used for Kubernetes API access and Workload Identity.
Here: `api`, `frontend`; tokens not mounted.

**23. What is a namespace?**
Short: a logical partition of a cluster.
Detail: scopes names, quotas, RBAC and NetworkPolicy.
Here: `travel-planner`.

**24. What is Kustomize?**
Short: template-free YAML customisation with bases and overlays.
Detail: built into `kubectl apply -k`.
Here: `base/`, `overlays/local`, `overlays/gke`.

**25. Why overlays instead of copies?**
Short: avoid duplicated YAML drift.
Detail: copies drift; overlays patch only what differs per environment.
Here: only real differences live in overlays (images, secrets, ingress, env).

**26. How do you debug a pod that won't become Ready?**
Short: `kubectl describe pod` (events, probes), `kubectl logs`.
Detail: Events show probe failures, image pulls and mount errors.
Here: usually missing keys (readiness 503).

**27. What is `CrashLoopBackOff`?**
Short: the container keeps exiting; Kubernetes backs off restarts.
Detail: check `logs --previous`.
Here: e.g. invalid settings fail at startup.

**28. What is `ImagePullBackOff`?**
Short: the image can't be pulled.
Detail: wrong name, missing image, or no registry permission.
Here: forgot `kind load`, or the node lacks `artifactregistry.reader`.

**29. How did you validate the manifests without a cluster?**
Short: kustomize render + kubeconform strict with CRD schemas, plus consistency tests.
Detail: kubeconform checks resources against the official API schemas; tests check app consistency.
Here: 31/31 valid; 16 tests; same check in CI.

**30. What would you verify first on a real cluster?**
Short: pods Ready, probes, UI→API connectivity, secrets, NetworkPolicy, HPA metrics, pod deletion recovery.
Detail: those confirm configuration, networking and self-healing assumptions that static checks can't.
Here: checklist in docs/23.

## GCP / GKE (30)

**1. What is GKE?**
Short: Google's managed Kubernetes.
Detail: Google runs the control plane; Autopilot also manages nodes.
Here: target platform (documented only).

**2. Autopilot vs Standard?**
Short: Google manages nodes and you pay per pod requests, vs you manage node pools.
Detail: Autopilot enforces security defaults and has Workload Identity built in.
Here: Autopilot chosen for simplicity.

**3. What is a node pool?**
Short: a group of nodes with the same machine configuration.
Detail: Standard clusters manage them explicitly.
Here: Autopilot manages them.

**4. What is Artifact Registry?**
Short: GCP's private package and image registry.
Detail: IAM-controlled, regional.
Here: `REGION-docker.pkg.dev/PROJECT_ID/travel-planner/{api,frontend}`.

**5. Tag vs digest?**
Short: a movable label vs an immutable content hash.
Detail: digests guarantee exact bytes.
Here: tags = git SHA, so each deploy is traceable.

**6. How does GKE pull private images?**
Short: with the node's service account.
Detail: needs `roles/artifactregistry.reader`.
Here: noted in docs/24 for `ImagePullBackOff`.

**7. What is Secret Manager?**
Short: encrypted, versioned, audited secret storage.
Detail: IAM per secret; rotation by adding versions.
Here: `gemini-api-key`, `tavily-api-key`.

**8. How do pods get Secret Manager secrets?**
Short: the GKE Secret Manager add-on mounts them as files via CSI.
Detail: authorised through Workload Identity.
Here: `/var/secrets/*`, read via `SECRETS_DIR`.

**9. Why not plain Kubernetes Secrets in production?**
Short: weaker controls.
Detail: base64 in etcd, cluster-wide RBAC, no versioning or audit by default.
Here: used only for local clusters.

**10. What is Workload Identity?**
Short: pods act as a Google identity without key files.
Detail: short-lived tokens issued by the platform.
Here: `ns/travel-planner/sa/api` can read only its two secrets.

**11. Why are JSON service-account keys dangerous?**
Short: long-lived bearer credentials that leak easily.
Detail: anyone holding the file has access until it's revoked.
Here: none anywhere in the design.

**12. What is Workload Identity Federation for GitHub?**
Short: GitHub's OIDC token is exchanged for short-lived GCP credentials.
Detail: an attribute condition restricts which repository may use it.
Here: `deploy.yml` with `id-token: write`.

**13. What IAM roles does the deployer need?**
Short: `container.developer` and Artifact Registry writer.
Detail: least privilege; nothing project-wide beyond that.
Here: `gh-deployer` service account.

**14. What does the Ingress create on GKE?**
Short: a Google Cloud HTTP(S) load balancer.
Detail: health checks, NEG-based routing to pods.
Here: the UI only.

**15. What is a BackendConfig?**
Short: a GKE CRD to tune load balancer backends.
Detail: timeouts, health checks, session affinity, Cloud Armor.
Here: 1 h timeout for Streamlit websockets, cookie affinity.

**16. Why raise the backend timeout?**
Short: the default 30 s would cut Streamlit's websocket.
Detail: the load balancer closes connections idle longer than the backend timeout.
Here: `timeoutSec: 3600`.

**17. How do you get HTTPS?**
Short: a ManagedCertificate plus a static IP and DNS.
Detail: Google provisions and renews the certificate once DNS points to the IP.
Here: `managed-certificate.yaml` (optional).

**18. What is Cloud Armor?**
Short: a WAF and rate limiting at the load balancer.
Detail: sees real client IPs.
Here: recommended for per-user rate limits (docs/25).

**19. How does logging work on GKE?**
Short: the agent collects container stdout to Cloud Logging.
Detail: JSON lines become `jsonPayload`; `severity` sets the level.
Here: the formatter emits `severity`.

**20. Why not run ELK on GKE?**
Short: Cloud Logging already does it, managed.
Detail: ELK would add a stateful cluster to operate.
Here: ELK local, Cloud Logging in GCP.

**21. What is a log-based metric?**
Short: a metric counted from matching log entries.
Detail: usable in Cloud Monitoring charts and alerts.
Here: `llm_call_failures` example in docs/24.

**22. How would you alert on problems?**
Short: alerting policies on log-based metrics and uptime checks.
Detail: alert on symptoms users feel (errors, latency) and on cost-relevant signals.
Here: LLM failures, `ITINERARY_INVALID`, 5xx rate.

**23. Which APIs must be enabled?**
Short: container, artifactregistry, secretmanager, iamcredentials, sts, logging, monitoring.
Detail: services are off by default per project.
Here: docs/24 §1.

**24. Why is billing required?**
Short: GKE, load balancing and registry storage are paid.
Detail: set a budget alert first.
Here: noted at the top of docs/24.

**25. What drives GCP cost here?**
Short: pod requests, the load balancer, logging volume.
Detail: LLM and search usage likely dominate overall.
Here: listed in docs/24 §8.

**26. How do you roll back on GKE?**
Short: `kubectl rollout undo`.
Detail: Deployments keep previous ReplicaSets for this.
Here: automatic on failure in `deploy.yml`.

**27. How do you rotate a secret?**
Short: add a new version, then restart the pods.
Detail: CSI mounts read the latest version at pod start.
Here: `gcloud secrets versions add` + `kubectl rollout restart deploy/api`.

**28. What is VPC-native networking?**
Short: pods get IPs from the VPC.
Detail: required for NEGs and container-native load balancing.
Here: Autopilot default.

**29. How would you use Gemini without an API key?**
Short: Vertex AI with Workload Identity.
Detail: Vertex AI authenticates with IAM, so pods use Workload Identity instead of a key.
Here: future change in the LLM factory.

**30. What was actually done on GCP?**
Short: nothing executed: design, YAML and commands are documented.
Detail: no project or credentials were available.
Here: labelled DOCUMENTED ONLY.

## CI/CD (25)

**1. What is CI?**
Short: automatically build and test every change.
Detail: catches breakage within minutes.
Here: `ci.yml` on every PR and push to main.

**2. What is CD?**
Short: automatically release tested changes.
Detail: delivery = ready to deploy; deployment = deployed automatically.
Here: `deploy.yml` after CI succeeds on main.

**3. What runs on a pull request?**
Short: lint, tests, demo evaluation, pip-audit, manifest validation.
Detail: fast, free, needs no secrets.
Here: jobs `test`, `dependency-audit`, `manifests`.

**4. Why are Docker builds on main only?**
Short: slower; image problems matter once code merges.
Detail: builds take minutes and need Docker; PR feedback should stay fast.
Here: `if: github.event_name != 'pull_request'`.

**5. Why isn't live LLM evaluation in CI?**
Short: it costs credits and depends on today's web.
Detail: noisy results would teach people to ignore red builds.
Here: `eval-live.yml`, manual only.

**6. Why `--report-only` for demo evaluation?**
Short: expected demo failures shouldn't fail CI.
Detail: demo data has no adventure/nature places, so `preference_match` fails by design.
Here: the report is uploaded as an artifact.

**7. How are dependencies cached?**
Short: setup-python pip cache keyed on the requirements files.
Detail: reinstalling identical wheels on every run wastes minutes.
Here: `cache-dependency-path`.

**8. What does the container smoke test check?**
Short: health, readiness, a real `/plan` in demo mode, uid 10001, no `.env` in the image.
Detail: proves the image actually starts, serves and respects its security properties.
Here: the `images` job.

**9. What is Trivy?**
Short: a vulnerability scanner for images and files.
Detail: fails on fixable CRITICAL/HIGH findings.
Here: scans both images.

**10. What is pip-audit?**
Short: checks Python dependencies against advisory databases.
Detail: uses the PyPA advisory database / OSV; reports affected versions and fixes.
Here: both images' requirements; currently no known vulnerabilities.

**11. Why hadolint?**
Short: catches Dockerfile mistakes and bad practices.
Detail: a Dockerfile linter based on best-practice rules.
Here: found WORKDIR and numeric-USER issues, now fixed.

**12. How are manifests validated in CI?**
Short: `kubectl kustomize` + `kubeconform -strict`.
Detail: catches typos, wrong API versions and invalid fields before any cluster sees them.
Here: both overlays, with CRD schemas.

**13. How does deploy authenticate to GCP?**
Short: Workload Identity Federation (OIDC), no stored key.
Detail: GitHub issues an OIDC token; Google exchanges it for short-lived credentials.
Here: `google-github-actions/auth@v3`.

**14. What is the simple, not recommended alternative?**
Short: a JSON key in a GitHub secret.
Detail: long-lived and leakable.
Here: `credentials_json` commented out.

**15. How do you prevent deploying untested code?**
Short: trigger on CI success for the same commit.
Detail: deploy only after the CI run for that commit concluded successfully.
Here: `workflow_run` + `conclusion == 'success'`.

**16. How do you add a manual approval?**
Short: GitHub Environment protection rules.
Detail: required reviewers must approve before the job runs.
Here: `environment: production`.

**17. How are images tagged?**
Short: by git SHA.
Detail: traceable; enables precise rollback.
Here: `api:$SHA`, `frontend:$SHA`.

**18. How does the pipeline fill placeholders?**
Short: `sed` in the ephemeral checkout before `kubectl apply -k`.
Detail: nothing environment-specific is committed.
Here: REGION, PROJECT_ID, REPLACE_WITH_GIT_SHA.

**19. How is a failed rollout handled?**
Short: `rollout status` times out → `rollout undo`.
Detail: readiness probes decide success; a timeout triggers the undo step.
Here: the final step in `deploy.yml`.

**20. Why `concurrency` groups?**
Short: cancel superseded CI runs; serialise deploys.
Detail: avoids wasted runs and two deploys racing each other.
Here: `ci-${{ github.ref }}`, `deploy-production`.

**21. Why least-privilege workflow permissions?**
Short: limit what a compromised step can do.
Detail: GitHub's token gets only the scopes listed in `permissions`.
Here: `contents: read`; deploy adds only `id-token: write`.

**22. How would you harden the supply chain further?**
Short: pin actions to commit SHAs, sign images, verify signatures.
Detail: tags can be moved by an attacker; commit SHAs can't.
Here: future improvement.

**23. How did you validate workflows locally?**
Short: actionlint, plus checking every action input against its `action.yml`.
Detail: actionlint checks syntax, expressions and known action inputs.
Here: no problems; test file enforces security rules.

**24. What is the CI status today?**
Short: never run on GitHub (no remote).
Detail: the repository has no GitHub remote yet.
Here: labelled NOT RUN.

**25. What will the first real CI run likely reveal?**
Short: Docker build or Trivy findings not visible locally.
Detail: nothing Docker-related has executed yet.
Here: fix and re-run.

## ELK (20)

**1. What is the ELK stack?**
Short: Elasticsearch (store/search), Logstash (pipeline), Kibana (UI).
Detail: a common open-source stack for centralised logs.
Here: the API's JSON logs → Logstash → Elasticsearch → Kibana.

**2. What is Elasticsearch?**
Short: a distributed search engine and document store built on Lucene.
Detail: documents in indices, inverted indexes for fast filtering and aggregation.
Here: one document per log event in `travel-planner-logs-YYYY.MM.DD`.

**3. What is an index?**
Short: a named collection of documents with a mapping.
Detail: physically split into shards.
Here: one index per day, so old days can be deleted.

**4. What is a mapping?**
Short: the schema: the type of each field.
Detail: dynamic mapping guesses types; explicit mapping avoids conflicts.
Here: numbers and booleans mapped explicitly; strings default to `keyword`; a test enforces coverage.

**5. `keyword` vs `text`?**
Short: exact values (filter, aggregate) vs analysed full-text.
Detail: `text` is tokenised; `keyword` keeps the whole value.
Here: `event_type`, `request_id` → keyword; `message` → text.

**6. What is an index template?**
Short: settings and mappings applied automatically to matching new indices.
Detail: composable templates with `index_patterns` and a priority.
Here: `travel-planner-logs.template.json`, installed by Logstash (`manage_template`).

**7. What are shards and replicas?**
Short: partitions of an index / copies for resilience.
Detail: a replica must live on a different node.
Here: 1 shard, 0 replicas (single local node).

**8. What is Logstash?**
Short: a pipeline with input, filter and output stages.
Detail: plugins for many sources and destinations.
Here: `file` input, `date` and `mutate` filters, `elasticsearch` output.

**9. Why parse JSON instead of grok?**
Short: the app already emits JSON.
Detail: grok regex parsing is brittle and slow.
Here: `codec => json`.

**10. Why does the `date` filter matter?**
Short: it sets `@timestamp` to when the event happened.
Detail: otherwise it's when Logstash read the line, which is wrong after a backlog.
Here: `match => ["timestamp","ISO8601"]`.

**11. What is the sincedb?**
Short: Logstash's record of how far it has read each file.
Detail: prevents re-ingesting after restarts.
Here: stored in the `logstash-data` volume.

**12. Why ship logs via a file and not a TCP appender?**
Short: decoupling; the app never blocks on logging infrastructure.
Detail: if Logstash is down, logs accumulate on disk and are read later.
Here: shared `app-logs` volume; on Kubernetes, stdout instead.

**13. What is Kibana?**
Short: the UI for Elasticsearch: Discover, Lens, dashboards.
Detail: data views define which indices and time field to use.
Here: data view `travel-planner-logs-*`, six saved searches.

**14. What is KQL?**
Short: Kibana Query Language for filtering.
Detail: `field : value`, `and/or/not`, ranges.
Here: `event_type : "request_completed" and status >= 400`.

**15. How would you chart p95 latency?**
Short: Lens → percentile of `latency_ms` over `@timestamp`.
Detail: filter to the route of interest.
Here: `/api/v1/plan` requests.

**16. How do you find all logs of one request?**
Short: search by correlation id.
Detail: sort ascending by time.
Here: `request_id : "<X-Request-ID>"`.

**17. What is retention and how would you implement it?**
Short: how long logs are kept; delete old data automatically.
Detail: Index Lifecycle Management (hot/warm/delete) or deleting daily indices.
Here: daily indices; ILM not configured locally (documented).

**18. Why is security disabled locally, and what would change in production?**
Short: convenience for local development only.
Detail: production needs TLS, authentication and roles.
Here: ports bound to 127.0.0.1 only; Stage 5 uses managed logging instead.

**19. Alternatives to ELK?**
Short: Cloud Logging, Loki + Grafana, OpenSearch, Datadog.
Detail: managed services trade cost for less operations work.
Here: on GKE, Cloud Logging collects stdout automatically.

**20. Why is ELK memory-hungry?**
Short: JVM heaps plus Lucene's file cache.
Detail: Elasticsearch wants about half of RAM for heap and half for OS cache.
Here: 512 MB ES heap, 256 MB Logstash; ELK is an optional compose profile.

## Observability (15)

**1. What is observability?**
Short: understanding a system's behaviour from the data it emits.
Detail: being able to answer new questions without shipping new code.
Here: JSON events, metrics, request-id correlation.

**2. Logs vs metrics vs traces?**
Short: individual events vs aggregates vs a timed path of one request.
Detail: logs give detail, metrics give trends cheaply, traces show where time goes across services.
Here: `llm_call` events, `/api/v1/metrics`; tracing only through a shared `request_id` (no tracing system).

**3. Why structured (JSON) logs?**
Short: fields can be queried directly.
Detail: avoids fragile regex parsing; types can be mapped in the index.
Here: `event_type : "llm_call" and not outcome : "ok"` in Kibana.

**4. What is a correlation id?**
Short: one id attached to every log line of a request.
Detail: lets you reconstruct a request across components; should be returned to the client.
Here: `request_id`, echoed in `X-Request-ID`.

**5. How does the id reach deeply nested code?**
Short: a `ContextVar`.
Detail: context variables are per-task; copied contexts share mutable objects.
Here: `request_id_var` and `RequestStats`; LangGraph nodes increment the shared counters.

**6. What must never be logged?**
Short: secrets, raw prompts, sensitive free text.
Detail: logs are widely accessible and long-lived.
Here: secret-looking fields dropped by the formatter and again by Logstash; prompts and `special_requirements` never logged.

**7. What is LLM observability?**
Short: tracking model calls: latency, outcome, tokens, cost, retries.
Detail: model behaviour changes without code changes, so it must be watched.
Here: `llm_call` events and `llm_calls_total{purpose,outcome}`.

**8. Why can token counts be null?**
Short: not every provider (or demo model) reports usage.
Detail: recording 0 would make totals falsely low.
Here: unknown is `null`.

**9. How do you estimate cost honestly?**
Short: tokens × current price, only when both are known.
Detail: hard-coded prices go stale silently.
Here: optional `LLM_*_COST_PER_MILLION_USD`; otherwise `estimated_cost_usd: null`.

**10. How do you measure repair effectiveness?**
Short: first-draft failure rate and repair success rate.
Detail: rate = success / (success + gave up).
Here: `itinerary_first_draft_total{result}`, `repair_success_total`, `itinerary_invalid_total`.

**11. What is metric cardinality?**
Short: the number of distinct label combinations.
Detail: unbounded labels (ids, free text) blow up memory and storage.
Here: route templates and enum labels only; never request ids or destinations as labels.

**12. Why not log health checks?**
Short: frequent, low-value noise.
Detail: still counted in metrics.
Here: health and metrics routes are skipped by the request logger.

**13. Limitation of in-process metrics?**
Short: per container, reset on restart.
Detail: production systems export to Prometheus or Cloud Monitoring.
Here: documented; ELK holds the durable history.

**14. How are log levels chosen?**
Short: INFO normal, WARNING client/recoverable, ERROR server failures.
Detail: alerting usually keys on ERROR.
Here: 5xx → ERROR, 4xx → WARNING; failed LLM calls → WARNING.

**15. How would you add tracing?**
Short: OpenTelemetry spans exported to Jaeger or Cloud Trace.
Detail: spans per operation with parent/child timing.
Here: natural spans are the LangGraph nodes and the `search`/`generate` calls.

## System design (30)

**1. Describe the architecture in one sentence.**
Short: a stateless FastAPI service orchestrating search and LLM calls through LangGraph, with code-based verification, behind a Streamlit UI.
Detail: deterministic code surrounds the probabilistic parts.
Here: ARCHITECTURE.md §0.

**2. Why stateless?**
Short: any replica can serve any request.
Detail: horizontal scaling and recovery become trivial.
Here: no database; each request is independent.

**3. What are the main bottlenecks?**
Short: LLM latency, then search.
Detail: our own code is ~30 ms per plan.
Here: planning and repair calls dominate.

**4. How would you scale to many users?**
Short: more API replicas, provider quota, caching, async jobs for long plans.
Detail: the true limits are provider rate limits and cost.
Here: HPA plus concurrency caps.

**5. Sync request vs background job?**
Short: background jobs suit tasks of tens of seconds or more.
Detail: return a job id and poll or stream; avoids timeouts.
Here: sync today; a queue is a future change.

**6. How would you cache?**
Short: cache research per destination and query for hours.
Detail: never share personalised plans across users.
Here: biggest cost saver; not built yet.

**7. Where is state if you add caching?**
Short: a shared store such as Redis or Memorystore.
Detail: per-pod caches fragment.
Here: would be the first stateful component.

**8. How do you handle partial failures?**
Short: degrade, flag and continue where safe; fail clearly where not.
Detail: decide per step whether missing data makes the result unsafe.
Here: one search fails → `partial`; all fail → real error code.

**9. How do you make failures visible?**
Short: stable error codes, logs and metrics per failure type.
Detail: a code per failure type lets dashboards and alerts distinguish causes.
Here: 12-row failure table in the final report.

**10. Why separate API and UI?**
Short: independent scaling, exposure and deploys.
Detail: different state models (stateless API vs session-holding UI).
Here: two images, two Deployments.

**11. Why not expose the API publicly?**
Short: it has no authentication.
Detail: reduces attack surface and cost abuse.
Here: ClusterIP + NetworkPolicy.

**12. How do you protect cost?**
Short: rate limits, concurrency caps, bounded retries and repairs.
Detail: every limit is configuration, visible in metrics.
Here: 20/min per client, 8 concurrent per replica, ≤ 2 repairs.

**13. Idempotency?**
Short: a plan request has no side effects, so retrying is safe.
Detail: retries only cost money.
Here: no writes anywhere.

**14. How do you version contracts?**
Short: URL version plus versioned prompts and schemas.
Detail: breaking changes go to a new version; old clients keep working.
Here: `/api/v1`, prompt version constants.

**15. How do you keep config, secrets and code apart?**
Short: env vars and mounted files; nothing baked into images.
Detail: the same image runs in every environment with different configuration.
Here: ConfigMap, Secret Manager, `.env` locally.

**16. How do you observe a single request?**
Short: a correlation id across all logs.
Detail: the id is returned to the client and appears in every event.
Here: `X-Request-ID` → `request_id` in every event.

**17. What SLOs would you set?**
Short: availability, p95 latency, valid-plan rate.
Detail: set targets after measuring.
Here: `ITINERARY_INVALID` rate as a quality SLO.

**18. How would you load test?**
Short: demo mode for infrastructure limits; small live samples for provider behaviour.
Detail: watch latency, 429s, memory.
Here: not done yet.

**19. Why no database?**
Short: nothing needs to persist.
Detail: add one when saved trips or user accounts exist.
Here: deliberate.

**20. Why no message queue?**
Short: requests are synchronous and short enough today.
Detail: add one for long jobs or retries.
Here: deliberate.

**21. Multi-region?**
Short: not needed now.
Detail: stateless makes it easy later: global load balancer + regional clusters.
Here: not needed for this project; the design would allow it.

**22. How do you handle provider outages?**
Short: clear errors and backoff; optionally fail over providers.
Detail: abstraction makes failover a configuration change.
Here: Serper is a ready alternative behind the same interface.

**23. Why abstractions for search and LLM?**
Short: swap providers and test with fakes.
Detail: interfaces isolate vendor details from the workflow.
Here: `SearchProvider`, `BaseChatModel`.

**24. Biggest design trade-off?**
Short: strict grounding vs coverage.
Detail: fewer but verified places, and "unknown" instead of guesses.
Here: users may see fewer prices.

**25. How would you add user accounts?**
Short: IAP or OIDC login at the edge; per-user rate limits; a database for saved trips.
Detail: identity at the edge, quotas per user, persistence for user data.
Here: not built; the API is internal and the UI anonymous today.

**26. How would you support streaming results?**
Short: SSE or websockets emitting partial state per node.
Detail: users see progress instead of waiting tens of seconds.
Here: LangGraph can stream node updates.

**27. How would you A/B test prompts?**
Short: route a share of traffic to a variant; compare evaluation and online quality metrics.
Detail: compare on the same metrics; keep variants versioned.
Here: prompt versions in logs.

**28. What would you monitor first in production?**
Short: 5xx rate, p95 latency, LLM failures, `ITINERARY_INVALID` rate, cost per plan.
Detail: user-facing symptoms first, then cost and quality signals.
Here: all available from logs and metrics already emitted.

**29. What's over-engineered here, honestly?**
Short: ELK plus Cloud Logging, and the Serper provider, for a project this size.
Detail: both are optional and justified as local tooling and an abstraction proof.
Here: Serper and ELK are both optional and documented as such.

**30. What's under-engineered?**
Short: authentication, tracing, real load and live evaluation.
Detail: these are the gaps between a verified prototype and a production service.
Here: listed as limitations.

## Security (20)

**1. How are API keys protected?**
Short: env or Secret Manager only; `SecretStr`; never logged, baked into images or committed.
Detail: keys are masked in reprs and only read where needed.
Here: tests and gitleaks confirm.

**2. How do you prevent secret leaks in logs?**
Short: don't pass them; redact secret-looking fields; drop them again in Logstash.
Detail: defence in depth: three independent layers.
Here: tested with fake keys.

**3. How do you validate input?**
Short: strict schemas at the boundary.
Detail: reject before spending money or reaching the LLM.
Here: Pydantic with `extra="forbid"`, character rules, length caps, enums.

**4. What is prompt injection?**
Short: untrusted text that tries to change the model's instructions.
Detail: from users or retrieved pages.
Here: delimiters, data-not-instructions rules, code verification.

**5. Why can't prompts alone stop injection?**
Short: models may still comply.
Detail: so code verifies outputs regardless.
Here: grounding and id-only planning.

**6. How do you avoid error leakage?**
Short: generic messages with stable codes; details stay in logs.
Detail: messages for users, stack traces for logs.
Here: the 500 handler.

**7. What is your CORS policy?**
Short: off by default; explicit origins only; `*` refused in prod.
Detail: CORS only matters for browsers calling the API directly.
Here: `CORS_ALLOW_ORIGINS`.

**8. How do you limit abuse?**
Short: rate and concurrency limits now; Cloud Armor at the edge in production.
Detail: in-app limits are per replica; the edge sees real client IPs.
Here: `app/api/limits.py`.

**9. Why validate client request ids?**
Short: to prevent log injection.
Detail: attacker-controlled ids could forge log lines.
Here: `[A-Za-z0-9-]{8,64}` only.

**10. How do you secure containers?**
Short: slim base, non-root, no secrets, scanned.
Detail: fewer packages and privileges mean less to exploit.
Here: uid 10001, Trivy, hadolint.

**11. How do you secure pods?**
Short: restrictive securityContext and NetworkPolicy.
Detail: limits what a compromised pod can do and reach.
Here: read-only FS, drop ALL capabilities, seccomp, default deny.

**12. Why block the metadata server?**
Short: it can hand out cloud credentials.
Detail: the app never needs it.
Here: NetworkPolicy excludes `169.254.169.254`.

**13. How do you handle dependency vulnerabilities?**
Short: pin, audit, update.
Detail: exact pins make audits meaningful and upgrades deliberate.
Here: pip-audit locally and in CI.

**14. How do you avoid long-lived credentials?**
Short: Workload Identity for pods and CI.
Detail: credentials that expire within an hour can't be leaked for long-term use.
Here: no JSON keys anywhere.

**15. How do you protect the UI from malicious content?**
Short: escape Markdown and HTML; http(s) links only.
Detail: LLM and web text may contain markup or links.
Here: `md_escape`, link columns, URL validation.

**16. What's the biggest security gap?**
Short: no end-user authentication.
Detail: anyone with the URL can use the service and spend quota.
Here: add IAP before public use.

**17. Why refuse demo mode in prod?**
Short: invented data must never reach real users.
Detail: demo data is invented and must never look like real advice.
Here: production guard in Settings.

**18. How are production misconfigurations caught?**
Short: fail fast at startup with clear messages.
Detail: validators run when Settings are built.
Here: `_production_guard`.

**19. How do you scan for committed secrets?**
Short: gitleaks.
Detail: scans files for credential patterns; findings in third-party packages were checked and excluded.
Here: 0 findings in project files.

**20. What would a security reviewer ask next?**
Short: authentication, audit logging of access, image signing, SHA-pinned actions, penetration tests.
Detail: the current design covers secrets, input and containment, not identity or provenance.
Here: listed as future work.

## Project-specific (40)

**1. What was the Stage 3 grounding gap and how did you fix it?**
Short: a generic activity could name an unverified venue in its free-text title; now activities are `place_id` XOR `generic_kind`, titles are code-generated, and free text is checked for unverified place names.
Detail: structural first (no free-text title), detector second; a keyword blacklist would always be incomplete.
Here: `planning/named_places.py`, `titles.py`, the validator's `UNSUPPORTED_NAMED_PLACE`.

**2. How does the named-place detector work?**
Short: finds runs of 2+ capitalised words and requires them to appear in verified research.
Detail: sentence-initial verbs tolerated; possessives handled; accent/case-insensitive.
Here: "Then head to Imaginary Palace" → flagged → repair.

**3. What are its limits?**
Short: lower-case names are missed; capitalised generic phrases cause false positives.
Detail: false positives cost a repair round; the prompt asks for sentence case.
Here: documented; Faithfulness evaluation is the backstop.

**4. Why is evidence limited to verified entities?**
Short: "traceable to verified research" excludes places merely mentioned in raw search text.
Detail: a source may mention a place in passing; only entities that passed grounding were checked against their source.
Here: `research_evidence()`; a regression test proves an unverified mention is rejected.

**5. Which metrics are code and which are judge-based, and why?**
Short: facts and arithmetic → code; subjective quality → judge.
Detail: code answers exact questions (ids, counts, sums) for free; judges handle coherence, usefulness, fit and faithfulness.
Here: 7 code metrics, 4 judge metrics.
Here: `metrics/deterministic.py` vs `metrics/judge.py`.

**6. What did your evaluation actually show?**
Short: demo only: 8/10 cases pass all metrics; preference gaps correctly detected; no live or judge scores.
Detail: demo scores measure mechanics on invented data, not model quality.
Here: `docs/19` with the exact numbers.

**7. Why must evaluation modes be explicit?**
Short: a live evaluation silently using demo data would produce meaningless scores.
Detail: there is no fallback; the report records the mode and a notice.
Here: `--mode` is required; live without keys exits.

**8. What happens per request in the logs?**
Short: 5 `search_call`, `research_grounded`, `llm_call`s, `itinerary_validated` (+ repair), `plan_completed`, `request_completed`, all sharing one `request_id`.
Detail: correlation by `request_id` reconstructs the request's path in order, with each step's latency.
Here: try it with `X-Request-ID: my-trace-0001` and search that id in Kibana.

**9. How do you answer "how often does the LLM produce an invalid itinerary?"**
Short: `itinerary_first_draft_total{result=invalid}` / total.
Detail: attempt 0 is the first draft; later attempts are post-repair validations.
Here: in ELK, `itinerary_validated` with `attempt:0 and passed:false`.

**10. "How often does repair fix it?"**
Short: `repair_success_total / (repair_success_total + itinerary_invalid_total)`.
Detail: "gave up" counts plans that still failed after `MAX_REPAIR_ATTEMPTS` repairs.
Here: in ELK, compare `itinerary_validated` (attempt > 0, passed) with `itinerary_invalid` events.

**11. Why is LLM cost null by default?**
Short: prices change; an unconfigured rate would give confident wrong numbers.
Detail: tokens are logged whenever the provider reports them, so cost can also be computed later from logs.
Here: set `LLM_*_COST_PER_MILLION_USD` to enable.

**12. How did you make sure logs never leak keys?**
Short: keys are never passed to the logger; the formatter drops secret-looking fields; Logstash drops them again.
Detail: defence in depth: three independent layers.
Here: tests put fake keys in configs and assert they never appear in logs.

**13. Why does the API write a log file as well as stdout?**
Short: for Logstash in docker-compose; stdout is for Docker and Kubernetes.
Detail: the file is the decoupled hand-off to Logstash through a shared volume.
Here: `LOG_FILE` is optional and set only by compose.

**14. How do you know the index mapping matches the app?**
Short: a test runs a demo request and asserts every non-string logged field is mapped.
Detail: unmapped numeric fields would be guessed by dynamic mapping and could conflict across daily indices.
Here: `test_every_non_string_field_the_app_logs_has_an_explicit_mapping`.

**15. Where is the application slow, and where does it cost money?**
Short: external calls; our code is ~30 ms (measured in demo).
Detail: real Gemini and Tavily latency was not measured (no keys); every live call logs its latency and tokens.
Here: `docs/18_observability.md`, Cost and performance section.

**16. How would you cut LLM calls?**
Short: fewer repairs (better prompts, targeted fixes), smaller inputs, and caching research.
Detail: each repair repeats most of the planning cost; research input dominates extraction tokens.
Here: watch `validation_failures_total{code}` to see which rule fails.

**17. Why is ELK optional in compose?**
Short: ~3 GB RAM; developers rarely need it.
Detail: API + UI run in a few hundred MB; ELK needs JVM heaps and caches.
Here: `--profile elk`.

**18. What did you verify about Docker and ELK?**
Short: static configuration tests and a fake-curl payload test; no container was run.
Detail: Docker wasn't installed; reported as NOT RUN.
Here: `tests/unit/test_container_config.py`, `docs/20`–`22` (run procedures).

**19. Why add `/api/v1/research` and keep `/plan`?**
Short: evaluate and debug research alone.
Detail: research problems (bad sources, rejected entities) are easier to see without planning on top.
Here: `evaluation/test_research.py` uses it.

**20. What is the next step for observability?**
Short: OpenTelemetry tracing, Prometheus or Cloud Monitoring metrics, alerting.
Detail: logs + metrics + traces together give the full picture; alerts make them actionable.
Here: Stage 5 uses Cloud Logging and Cloud Monitoring on GKE.

**21. Walk me through one request.**
Short: validate → 5 searches → extract → ground → plan → optimize → validate ⇄ repair → assemble → budget → respond, all logged with one request id.
Detail: each step has a typed input and output.
Here: docs/FINAL_REQUEST_FLOW.md.

**22. Why is the budget not done by the LLM?**
Short: arithmetic has one right answer; code is exact and free.
Detail: LLM math errors are confident and hard to spot.
Here: `planning/budget.py`; tests check the sums.

**23. What happens if Gemini is down?**
Short: the call fails → 502 `LLM_ERROR` (or 504/429), logged as `llm_call` with its outcome.
Detail: the SDK retries transient errors first.
Here: failure table rows 5–6.

**24. What happens if Tavily is down?**
Short: all categories fail → the real error code; some fail → `partial` with warnings.
Detail: per-category errors are kept; the system degrades rather than inventing data.
Here: failure table rows 3–4.

**25. How do you know repair works?**
Short: metrics: first-draft invalid rate vs repair success vs gave up.
Detail: demo mode exercises it on every request.
Here: `repair_success_total`, `itinerary_invalid_total`.

**26. Why does demo mode exist, and how is it kept honest?**
Short: run without keys; every response labelled demo; refused in prod; never automatic.
Detail: the same code path runs with offline stand-ins.
Here: `.invalid` URLs, "Sample" names, DEMO banner.

**27. How do the frontend and API communicate in Kubernetes?**
Short: via the API Service's DNS name, configured in a ConfigMap.
Detail: no cluster-specific IPs in code.
Here: `http://api.travel-planner.svc.cluster.local:8000`.

**28. How are secrets delivered on GKE?**
Short: Secret Manager → CSI files → `SECRETS_DIR` → Settings.
Detail: Workload Identity authorises only the api ServiceAccount.
Here: `overlays/gke/`.

**29. What did you verify about Kubernetes?**
Short: rendering, strict schema validation, consistency tests. No cluster run.
Detail: static checks only; no pod has run.
Here: 31/31 valid; NOT RUN on a cluster.

**30. What are the readiness semantics?**
Short: ready = configured providers have their keys.
Detail: no external calls; cheap and safe to poll.
Here: `/api/v1/health/ready`.

**31. What did measuring show?**
Short: startup 1.6 s, ~116 MiB RSS idle, ~30 ms own overhead per plan (demo).
Detail: real API latency unmeasured.
Here: used to set resource requests.

**32. Which part was hardest to get right?**
Short: deterministic grounding without blacklists.
Detail: name matching tolerant of case, accents and possessives; and the named-place check's false-positive balance.
Here: `grounding.py`, `named_places.py`.

**33. A bug your tests caught?**
Short: several: newline injection in place names, comma-separated CORS env crashing startup, the empty cost env var crashing startup.
Detail: each was found by a failing test or an audit check, then covered by a regression test.
Here: regression tests exist for each.

**34. What would you remove if simplifying?**
Short: the Serper provider and the ELK profile.
Detail: they're optional; the core works without them.
Here: neither affects the core request path.

**35. Why a production configuration guard?**
Short: unsafe settings fail at startup, not in front of users.
Detail: misconfiguration becomes a deploy failure, not a user-facing incident.
Here: demo mode, CORS `*`, text logs refused in prod.

**36. How is the API protected from overload?**
Short: per-client rate limit, per-replica concurrency cap, HPA.
Detail: limits return fast 429s instead of slow timeouts.
Here: 429 with `Retry-After`.

**37. What's the deployment rollback story?**
Short: rolling update with `maxUnavailable: 0`; `rollout undo` on failure.
Detail: capacity never drops during a deploy; failures revert automatically.
Here: automatic in `deploy.yml`.

**38. What's not production-ready?**
Short: no auth, no real-load data, never run on real APIs or infrastructure.
Detail: the gaps are operational verification and identity, not core logic.
Here: FINAL_PROJECT_REPORT.md → Limitations.

**39. What would you do in the first week with real keys and a cluster?**
Short: live tests, live evaluation with judge, kind deploy, CI run, measure latency and cost, fix findings.
Detail: turn every NOT RUN into a measured result.
Here: README status table becomes VERIFIED row by row.

**40. Why should we believe your results?**
Short: every claim is labelled VERIFIED, NOT RUN or DOCUMENTED ONLY, and backed by tests or commands in the repo.
Detail: I prefer an honest "not run" over an unverified "works".
Here: FINAL_PROJECT_REPORT.md.
