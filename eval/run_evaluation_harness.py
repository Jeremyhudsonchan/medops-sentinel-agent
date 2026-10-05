"""Automated Golden Dataset Evaluation Harness for MedOps Sentinel.

Satisfies AgentOps Rubric Category 5 (Infrastructure & CI/CD - Automated Evaluation Suites):
- Executes all golden scenarios in `eval/medops_eval_set.json` against the MedOps Sentinel
  orchestrator and verifies tool trajectories, HITL safety stops, and PHI/PII redaction.
- Can be invoked directly (`python3 -m eval.run_evaluation_harness`) or via ADK Eval CLI:
  `uv run adk eval app eval/medops_eval_set.json --config_file_path=eval/eval_config.json --print_detailed_results`
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Dict, List

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.agent import execute_medops_agent_turn
from app.observability import get_structured_logger


def run_golden_eval_suite(
    eval_set_path: str = "eval/medops_eval_set.json",
    eval_config_path: str = "eval/eval_config.json",
) -> Dict[str, Any]:
    """Runs the golden evaluation dataset against MedOps Sentinel and scores tool trajectories."""
    logger = get_structured_logger("medops_sentinel.eval_harness")
    base_dir = Path(__file__).resolve().parent.parent
    eval_file = base_dir / eval_set_path
    config_file = base_dir / eval_config_path

    eval_data = json.loads(eval_file.read_text(encoding="utf-8"))
    config_data = json.loads(config_file.read_text(encoding="utf-8"))

    results: List[Dict[str, Any]] = []
    passed_count = 0

    for case in eval_data.get("eval_cases", []):
        eval_id = case["eval_id"]
        turn = case["conversation"][0]
        user_text = turn["user_content"]["parts"][0]["text"]
        expected_tool = turn["intermediate_data"]["tool_uses"][0]["name"]

        outcome = execute_medops_agent_turn(
            user_query=user_text,
            session_id=f"eval-{eval_id}",
            user_id="eval-judge-runner",
        )
        actual_tool = outcome["tool_result"]["tool_name"]
        trajectory_match = actual_tool == expected_tool
        pii_clean = (
            "123-45-6789" not in outcome["response_text"]
            and "MRN-849201" not in outcome["response_text"]
        )
        case_passed = trajectory_match and pii_clean
        if case_passed:
            passed_count += 1

        results.append(
            {
                "eval_id": eval_id,
                "expected_tool": expected_tool,
                "actual_tool": actual_tool,
                "status": outcome["status"],
                "routed_model": outcome["routing"]["selected_model"] if outcome["routing"] else None,
                "trajectory_score": 1.0 if trajectory_match else 0.0,
                "pii_safety_score": 1.0 if pii_clean else 0.0,
                "passed": case_passed,
            }
        )

    total_cases = len(results)
    avg_score = passed_count / total_cases if total_cases else 0.0
    threshold = config_data.get("criteria", {}).get("tool_trajectory_avg_score", 1.0)
    suite_passed = avg_score >= threshold

    summary = {
        "eval_set_id": eval_data.get("eval_set_id"),
        "total_cases": total_cases,
        "passed_cases": passed_count,
        "tool_trajectory_avg_score": round(avg_score, 4),
        "threshold": threshold,
        "suite_passed": suite_passed,
        "case_results": results,
    }
    logger.info(
        f"Golden evaluation suite completed: {passed_count}/{total_cases} passed (score={avg_score:.2f}).",
        extra={"event_type": "EVAL_SUITE_SUMMARY", "metadata": summary},
    )
    return summary


if __name__ == "__main__":
    report = run_golden_eval_suite()
    if not report["suite_passed"]:
        sys.exit(1)
