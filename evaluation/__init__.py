"""Offline LLM evaluation for the travel planner (DeepEval + deterministic metrics).

Run:  python -m evaluation.runner --mode demo        (no keys; pipeline mechanics only)
      python -m evaluation.runner --mode live --judge (real Tavily + Gemini + LLM judge)
"""

import os

# DeepEval sends anonymous usage telemetry by default; opt out before it is imported anywhere.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
