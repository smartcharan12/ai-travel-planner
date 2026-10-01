"""Run the evaluation dataset and write a JSON report.

    python -m evaluation.runner --mode demo                 # offline, invented data
    python -m evaluation.runner --mode live                 # real Tavily + Gemini, deterministic metrics
    python -m evaluation.runner --mode live --judge         # + LLM-as-judge metrics (extra cost)
    python -m evaluation.runner --mode demo --cases goa_couple_beaches,delhi_business_one_day

Modes are explicit. There is no automatic fallback from live to demo: a
"live" evaluation that silently used invented data would report meaningless
scores.

What each mode measures:
- demo: the pipeline's MECHANICS (grounding rules, budget arithmetic, completeness,
  repair loop) on invented sample data. It says nothing about Gemini's quality, and
  the demo planner ignores interests, so preference metrics are expected to be low.
- live: the real system end to end. Scores reflect today's web results and model behaviour.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import __version__
from app.config import Settings
from app.core.exceptions import TravelPlannerError
from app.observability.logging import configure_logging
from app.prompts.planner_prompt import PLANNER_PROMPT_VERSION
from app.prompts.research_prompt import PROMPT_VERSION as RESEARCH_PROMPT_VERSION
from app.services.travel_planner import TravelPlanner
from evaluation.config import RESULTS_DIR, THRESHOLD_STATUS, all_thresholds
from evaluation.dataset import EvalCase, load_cases
from evaluation.metrics import deterministic_metrics, judge_metrics, judge_unavailable_reason
from evaluation.metrics.judge import judge_model_name
from evaluation.testcase_builder import build_test_case

MODE_NOTICES = {
    "demo": "DEMO EVALUATION: invented offline data and a rule-based demo model. Measures pipeline mechanics "
    "only; scores say NOTHING about real Gemini/Tavily quality.",
    "live": "LIVE EVALUATION: real Tavily search and Gemini model. Results depend on today's web content and "
    "model behaviour; repeat runs will differ.",
}


def _settings_for(mode: str) -> Settings:
    settings = Settings(demo_mode=True) if mode == "demo" else Settings()
    if mode == "live":
        if settings.is_demo:
            raise SystemExit("--mode live requested, but the configured providers are demo/fake.")
        missing = settings.missing_secrets()
        if missing:
            raise SystemExit(
                f"--mode live needs {', '.join(missing)} (set them in .env). Use --mode demo otherwise."
            )
    return settings


def _metric_result(metric: Any, kind: str) -> dict[str, Any]:
    return {
        "name": getattr(metric, "metric_name", None) or metric.__name__,
        "kind": kind,
        "score": metric.score,
        "threshold": metric.threshold,
        "passed": bool(metric.success) if metric.error is None else False,
        "explanation": metric.reason if metric.error is None else f"metric error: {metric.error}",
    }


async def _run_case(case: EvalCase, settings: Settings, use_judge: bool) -> dict[str, Any]:
    started = time.perf_counter()
    result: dict[str, Any] = {
        "case_id": case.id,
        "description": case.description,
        "tags": case.tags,
        "input": case.request.model_dump(mode="json"),
        "expected_behavior": case.expected_behavior,
    }
    try:
        response = await TravelPlanner(settings).run(case.request, request_id=f"eval-{case.id}")
    except TravelPlannerError as exc:
        result.update(
            status="error",
            error={"code": exc.code, "message": exc.public_message},
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            metrics=[],
        )
        return result

    test_case = build_test_case(case.id, case.request, response)
    metric_results = []
    for metric in deterministic_metrics():
        metric.measure(test_case)
        metric_results.append(_metric_result(metric, "deterministic"))
    if use_judge:
        for metric in judge_metrics(settings):
            try:
                metric.measure(test_case)
            except Exception as exc:  # a judge failure must not hide the deterministic results
                metric.error = f"{type(exc).__name__}"
            metric_results.append(_metric_result(metric, "llm_judge"))

    result.update(
        status="evaluated",
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        actual_output={
            "title": response.itinerary.title,
            "days": len(response.itinerary.days),
            "activities": sum(len(d.activities) for d in response.itinerary.days),
            "budget_total": response.budget.total,
            "within_budget": response.budget.within_budget,
            "repair_attempts": response.quality.repair_attempts,
            "warnings": response.warnings,
            "text": test_case.actual_output,
        },
        run_metadata=response.metadata.model_dump(mode="json"),
        metrics=metric_results,
    )
    return result


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        for m in c["metrics"]:
            by_metric.setdefault(m["name"], []).append(m)
    return {
        "cases_total": len(cases),
        "cases_evaluated": sum(c["status"] == "evaluated" for c in cases),
        "cases_errored": sum(c["status"] == "error" for c in cases),
        "cases_all_metrics_passed": sum(
            c["status"] == "evaluated" and all(m["passed"] for m in c["metrics"]) for c in cases
        ),
        "metrics": {
            name: {
                "mean_score": round(sum(m["score"] or 0 for m in ms) / len(ms), 4),
                "pass_rate": round(sum(m["passed"] for m in ms) / len(ms), 4),
                "n": len(ms),
            }
            for name, ms in by_metric.items()
        },
    }


def run(mode: str, *, use_judge: bool, only: list[str] | None, out_dir: Path) -> tuple[dict[str, Any], Path]:
    settings = _settings_for(mode)
    judge_reason = None
    if use_judge:
        judge_reason = (
            judge_unavailable_reason(settings) if mode == "live" else "NOT RUN: judge disabled in demo mode"
        )
        use_judge = judge_reason is None
    else:
        judge_reason = "NOT RUN: --judge not requested"

    cases = load_cases(only=only)
    started = datetime.now(UTC)
    results = [asyncio.run(_run_case(c, settings, use_judge)) for c in cases]
    report = {
        "report_version": 1,
        "timestamp": started.isoformat(),
        "mode": mode,
        "mode_notice": MODE_NOTICES[mode],
        "configuration": {
            "app_version": __version__,
            "git_sha": settings.git_sha,
            "model": "demo-model" if mode == "demo" else settings.llm_model,
            "search_provider": "demo" if mode == "demo" else settings.search_provider,
            "planner_prompt": PLANNER_PROMPT_VERSION,
            "research_prompt": RESEARCH_PROMPT_VERSION,
            "max_repair_attempts": settings.max_repair_attempts,
        },
        "judge": {
            "enabled": use_judge,
            "model": judge_model_name(settings) if use_judge else None,
            "status": "RUN" if use_judge else judge_reason,
        },
        "thresholds": all_thresholds(),
        "threshold_status": THRESHOLD_STATUS,
        "summary": _summary(results),
        "cases": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"eval-{started:%Y%m%dT%H%M%SZ}-{mode}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report, path


def _print(report: dict[str, Any], path: Path) -> None:
    print(report["mode_notice"])
    print(f"judge: {report['judge']['status']}   thresholds: {report['threshold_status']}\n")
    for c in report["cases"]:
        if c["status"] == "error":
            print(f"  ERROR {c['case_id']:<32} {c['error']['code']}")
            continue
        failed = [m["name"] for m in c["metrics"] if not m["passed"]]
        print(
            f"  {'PASS ' if not failed else 'FAIL '} {c['case_id']:<32} "
            + (f"failed: {', '.join(failed)}" if failed else "")
        )
    print("\n  metric                  mean   pass rate")
    for name, s in report["summary"]["metrics"].items():
        print(f"  {name:<22} {s['mean_score']:>5.2f}   {s['pass_rate']:>6.0%}  (n={s['n']})")
    print(f"\nreport: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=["demo", "live"], required=True)
    parser.add_argument(
        "--judge", action="store_true", help="also run LLM-as-judge metrics (live only, costs)"
    )
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="always exit 0 (CI artifact for demo runs, where some failures are expected)",
    )
    args = parser.parse_args()
    # Keep the console readable: only warnings and errors from the app, as text.
    configure_logging(level="ERROR", fmt="text")
    report, path = run(
        args.mode, use_judge=args.judge, only=args.cases.split(",") if args.cases else None, out_dir=args.out
    )
    _print(report, path)
    summary = report["summary"]
    if args.report_only:
        return 0
    return 0 if summary["cases_all_metrics_passed"] == summary["cases_total"] else 1


if __name__ == "__main__":
    sys.exit(main())
