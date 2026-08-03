"""Run fixed eval cases against the Smart Recipe Assistant.

Default mode is planner-only because it is faster and avoids web-search cost.
Use --mode full when you want to exercise the complete Agent pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
EVALS_DIR = ROOT_DIR / "evals"

for path in (SRC_DIR, EVALS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from evaluator import evaluate_case, load_cases, summarize_results  # noqa: E402


REPORTS_DIR = EVALS_DIR / "reports"
DEFAULT_MEMORY = {
    "diet_preferences": [],
    "allergies": [],
    "disliked_ingredients": [],
    "favorite_ingredients": [],
    "common_serving_size": "",
    "recent_dishes": [],
    "rejected_patterns": [],
    "updated_at": "",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Smart Recipe Assistant evals.")
    parser.add_argument(
        "--mode",
        choices=["plan", "full"],
        default="plan",
        help="plan checks only menu planning; full runs the complete Agent pipeline.",
    )
    parser.add_argument(
        "--agent",
        choices=["legacy", "graph"],
        default="legacy",
        help="legacy uses DeepResearchAgent; graph uses the LangGraph variant.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only a specific case id. Can be passed multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N selected cases.",
    )
    parser.add_argument(
        "--report-dir",
        default=str(REPORTS_DIR),
        help="Directory where eval JSON reports are saved.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print results without writing a report file.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first case execution error.",
    )
    parser.add_argument(
        "--search-api",
        default=None,
        help="Optional search backend override for full mode, e.g. duckduckgo or tavily.",
    )
    parser.add_argument(
        "--disable-notes",
        action="store_true",
        help="Disable NoteTool during eval runs to avoid creating note files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = select_cases(load_cases(), args.case_id, args.limit)
    if not cases:
        print("No eval cases selected.")
        return 1

    raw_outputs: dict[str, Any] = {}
    eval_results = []
    errors: list[dict[str, str]] = []

    for index, case in enumerate(cases, start=1):
        case_id = str(case["id"])
        print(f"[{index}/{len(cases)}] Running {case_id} ({args.mode})")

        try:
            output = run_case(case, args)
            raw_outputs[case_id] = output
            eval_case = case_for_mode(case, args.mode)
            eval_results.append(evaluate_case(eval_case, output))
        except Exception as exc:  # pragma: no cover - CLI safety net
            errors.append({"case_id": case_id, "error": str(exc)})
            raw_outputs[case_id] = {"error": str(exc)}
            print(f"  ERROR: {exc}")
            if args.fail_fast:
                break

    summary = summarize_results(eval_results)
    report = {
        "metadata": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": args.mode,
            "agent": args.agent,
            "case_count": len(cases),
        },
        "summary": summary,
        "errors": errors,
        "results": [result.to_dict() for result in eval_results],
        "raw_outputs": raw_outputs,
    }

    print_summary(summary, errors)
    if not args.no_save:
        report_path = save_report(report, Path(args.report_dir), args.mode, args.agent)
        print(f"Report saved: {report_path}")

    return 1 if errors else 0


def select_cases(
    cases: list[dict[str, Any]],
    case_ids: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    selected = cases
    if case_ids:
        wanted = set(case_ids)
        selected = [case for case in selected if case.get("id") in wanted]
        missing = wanted - {str(case.get("id")) for case in selected}
        if missing:
            raise ValueError("Unknown case id(s): " + ", ".join(sorted(missing)))

    if limit is not None:
        selected = selected[: max(limit, 0)]

    return selected


def run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    from config import Configuration
    from services.memory import MemoryService

    with tempfile.TemporaryDirectory(prefix="recipe_eval_") as tmp_dir:
        memory_path = Path(tmp_dir) / "user_memory.json"
        memory_service = MemoryService(memory_path=memory_path)
        memory = deepcopy(DEFAULT_MEMORY)
        memory.update(case.get("memory") or {})
        memory_service.save_memory(memory)

        config_overrides: dict[str, Any] = {}
        if args.search_api:
            config_overrides["search_api"] = args.search_api
        if args.disable_notes:
            config_overrides["enable_notes"] = False

        config = Configuration.from_env(overrides=config_overrides)

        if args.mode == "plan":
            if args.agent == "graph":
                raise ValueError("--agent graph currently supports --mode full only.")
            from agent import DeepResearchAgent

            agent = DeepResearchAgent(config=config)
            agent.memory = memory_service
            memory_context = memory_service.format_memory_for_prompt(memory)
            dish_list = agent.plan_menu(str(case.get("input") or ""), memory_context)
            return {
                "dish_list": dish_list,
                "shopping_list": [],
                "menu_markdown": "",
            }

        if args.agent == "graph":
            from services.graph_planner import GraphRecipeAgent

            result = GraphRecipeAgent(config=config, memory_service=memory_service).run(
                str(case.get("input") or "")
            )
        else:
            from agent import DeepResearchAgent

            agent = DeepResearchAgent(config=config)
            agent.memory = memory_service
            result = agent.run(str(case.get("input") or ""))
        return to_plain_data(result)


def case_for_mode(case: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "full":
        return case

    scoped = deepcopy(case)
    expected = scoped.setdefault("expected", {})
    required_outputs = expected.get("required_outputs")
    if isinstance(required_outputs, list):
        expected["required_outputs"] = [
            item for item in required_outputs if item == "dish_list"
        ]
    return scoped


def save_report(report: dict[str, Any], report_dir: Path, mode: str, agent: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"eval_{agent}_{mode}_{timestamp}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report_path


def print_summary(summary: dict[str, Any], errors: list[dict[str, str]]) -> None:
    print("")
    print("Eval summary")
    print(f"  Total evaluated: {summary.get('total', 0)}")
    print(f"  Passed: {summary.get('passed', 0)}")
    print(f"  Average score: {summary.get('average_score', 0.0):.2%}")
    if errors:
        print(f"  Execution errors: {len(errors)}")

    by_category = summary.get("by_category") or {}
    if by_category:
        print("")
        print("By category")
        for category, payload in by_category.items():
            total = payload.get("total", 0)
            passed = payload.get("passed", 0)
            score = payload.get("average_score", 0.0)
            print(f"  {category}: {passed}/{total}, avg {score:.2%}")


def to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {key: to_plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
