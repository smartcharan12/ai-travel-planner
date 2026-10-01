# evaluation/: LLM evaluation for the travel planner

Offline evaluation with [DeepEval](https://github.com/confident-ai/deepeval) plus deterministic, code-based
metrics. Full explanation: [`docs/19_deepeval.md`](../docs/19_deepeval.md). Beginner background:
[`docs/17_llm_evaluation_basics.md`](../docs/17_llm_evaluation_basics.md).

```text
evaluation/
├── README.md
├── config.py               thresholds (INITIAL ENGINEERING THRESHOLDS), judge model, paths
├── dataset.py              loads + validates cases into TravelRequest objects
├── datasets/
│   └── travel_cases.json   10 fixed inputs: Goa, Hyderabad, Jaipur, Delhi, Bengaluru; many styles
├── metrics/
│   ├── deterministic.py    code metrics (grounding, unsupported places, completeness, budget,
│   │                       preferences, constraints, research traceability)
│   └── judge.py            LLM-as-judge: DeepEval Faithfulness + 3 G-Eval rubrics (Gemini judge)
├── testcase_builder.py     response -> DeepEval LLMTestCase (input / actual_output / retrieval_context)
├── runner.py               python -m evaluation.runner  ->  results/eval-<time>-<mode>.json
├── conftest.py, pytest.ini  config for the pytest-style suites below
├── test_itinerary.py       deepeval test run evaluation/test_itinerary.py
├── test_research.py        deepeval test run evaluation/test_research.py
└── results/                JSON reports (git-ignored: they contain model output)
```

## Install

```bash
.venv/bin/pip install -r requirements-eval.txt   # deepeval is NOT part of the API image
```

## Run

| Command | Needs | Measures |
|---|---|---|
| `python -m evaluation.runner --mode demo` | nothing | pipeline mechanics on **invented** data |
| `python -m evaluation.runner --mode live` | `GEMINI_API_KEY`, `TAVILY_API_KEY` | the real system, deterministic metrics |
| `python -m evaluation.runner --mode live --judge` | same (+ extra LLM cost) | + LLM-as-judge metrics |
| `EVAL_MODE=demo deepeval test run evaluation/test_itinerary.py` | nothing | same metrics as pytest assertions |
| `EVAL_MODE=live EVAL_JUDGE=1 deepeval test run evaluation/` | keys | live + judge, itinerary + research |

There is **no automatic fallback** from live to demo. `--mode live` without keys exits with an error.

## Reading a report

Each case records the test input, the expected behaviour (written by a human), a summary of the actual output,
and, for each metric: `name`, `kind` (deterministic | llm_judge), `score`, `threshold`, `passed` and
`explanation`. Top-level fields: `timestamp`, `mode`, `mode_notice`, `configuration` (model, prompt versions,
git sha), `judge` (enabled, or the reason it was NOT RUN), `thresholds`, `threshold_status`, `summary`.

## Thresholds

`config.py` holds **INITIAL ENGINEERING THRESHOLDS**: developer-chosen starting points, not validated
benchmarks. Override any of them with `EVAL_THRESHOLD_<NAME>=…`. Tune them after collecting many live runs.
