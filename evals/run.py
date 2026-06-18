"""
Eval harness — exercises the real LLM against hand-crafted metric fixtures.

Requirements:
  - ANTHROPIC_API_KEY must be set in the environment.

Usage:
  uv run python -m evals.run           # run all cases
  uv run pytest evals/                 # same cases via pytest
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

_EVALS_DIR = Path(__file__).parent
_FIXTURES_DIR = _EVALS_DIR / "fixtures"
_CASES_FILE = _EVALS_DIR / "cases.yaml"


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    from app.config import Settings
    from app.insights.confidence import compute_confidence
    from app.insights.grounding import check_grounding
    from app.insights.llm import call_llm
    from app.insights.prompts import get_prompt

    fixture_path = _FIXTURES_DIR / case["fixture"]
    metrics = json.loads(fixture_path.read_text())
    window_days: int = case.get("window_days", 90)

    gini = metrics.get("gini", 0.0)
    totals = metrics.get("totals", {})
    conf_score, conf_rationale = compute_confidence(
        total_reviews=totals.get("reviews", 0),
        total_prs=totals.get("prs", 0),
        gini=gini,
        window_days=window_days,
    )

    settings = Settings(
        github_token="unused",
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        llm_enable_thinking=False,  # Disable thinking for faster evals
    )

    sys_prompt = get_prompt("insights", "system", 1).text
    user_tmpl = get_prompt("insights", "user", 1)
    user_prompt = user_tmpl.render(
        metrics_json=json.dumps(metrics, indent=2),
        confidence_score=conf_score,
        confidence_rationale=conf_rationale,
    )

    try:
        tool_output, usage = await call_llm(sys_prompt, user_prompt, settings)
        grounding = check_grounding(tool_output, metrics)
    except Exception as exc:
        return {"name": case["name"], "passed": False, "error": str(exc), "failures": []}

    failures: list[str] = []
    for assertion in case.get("assertions", []):
        if assertion == "tool_call_succeeded":
            pass  # reaching here means it succeeded

        elif assertion == "evidence_ids_valid":
            if not grounding.valid:
                failures.extend(grounding.failures)

        elif assertion == "numeric_grounding":
            numeric_failures = [f for f in grounding.failures if "numeric token" in f]
            failures.extend(numeric_failures)

        elif assertion == "no_hypothesis":
            if tool_output.hypothesis is not None:
                failures.append(
                    f"Expected no hypothesis for sparse data, got: {tool_output.hypothesis}"
                )

        elif isinstance(assertion, dict):
            if "confidence_gt" in assertion:
                threshold = assertion["confidence_gt"]
                if conf_score <= threshold:
                    failures.append(
                        f"confidence {conf_score} not > {threshold}"
                    )
            elif "confidence_lt" in assertion:
                threshold = assertion["confidence_lt"]
                if conf_score >= threshold:
                    failures.append(
                        f"confidence {conf_score} not < {threshold}"
                    )

    return {
        "name": case["name"],
        "passed": len(failures) == 0,
        "confidence": conf_score,
        "grounding_valid": grounding.valid,
        "failures": failures,
        "usage": usage,
    }


async def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set — skipping evals")
        return 1

    cases_raw = yaml.safe_load(_CASES_FILE.read_text())
    cases: list[dict[str, Any]] = cases_raw["cases"]

    print(f"\nRunning {len(cases)} eval cases...\n")
    print(f"{'Case':<25} {'Pass':<6} {'Conf':<6} {'Grounded':<10} {'Failures'}")
    print("-" * 80)

    all_passed = True
    for case in cases:
        result = await run_case(case)
        status = "✓" if result["passed"] else "✗"
        if not result["passed"]:
            all_passed = False

        failures_str = "; ".join(result.get("failures", []))[:40] or "–"
        print(
            f"{result['name']:<25} {status:<6} "
            f"{result.get('confidence', '?')!s:<6} "
            f"{str(result.get('grounding_valid', '?')):<10} "
            f"{failures_str}"
        )

        if result.get("error"):
            print(f"  ERROR: {result['error']}")

    print("-" * 80)
    print("All passed ✓" if all_passed else "Some cases failed ✗")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
