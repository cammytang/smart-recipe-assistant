"""Rule-based evaluators for Smart Recipe Assistant outputs.

The evaluator is intentionally model-free. It checks hard constraints that
should be stable across LLM providers: dish counts, banned ingredients,
required ingredients, report sections, memory metadata, and shopping list
deduplication.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Iterable


CASES_PATH = Path(__file__).with_name("cases.json")


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    score: float
    weight: float
    detail: str = ""


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    category: str
    passed: bool
    score: float
    checks: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "score": round(self.score, 4),
            "checks": [asdict(check) for check in self.checks],
        }


def load_cases(path: str | Path = CASES_PATH) -> list[dict[str, Any]]:
    """Load the fixed eval case set."""
    with Path(path).open("r", encoding="utf-8") as f:
        cases = json.load(f)

    if not isinstance(cases, list):
        raise ValueError("Eval cases must be a JSON list.")

    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(set(ids)):
        raise ValueError("Eval case ids must be unique.")

    return cases


def evaluate_cases(
    cases: Iterable[dict[str, Any]],
    outputs_by_case_id: dict[str, Any],
) -> list[EvalResult]:
    """Evaluate many outputs keyed by case id."""
    results: list[EvalResult] = []
    for case in cases:
        case_id = str(case.get("id") or "")
        output = outputs_by_case_id.get(case_id, {})
        results.append(evaluate_case(case, output))
    return results


def evaluate_case(case: dict[str, Any], output: Any) -> EvalResult:
    """Evaluate one agent output against one fixed case."""
    normalized = normalize_output(output)
    expected = case.get("expected") or {}

    checks: list[CheckResult] = []
    checks.append(check_required_outputs(expected, normalized))
    checks.append(check_dish_count(expected, normalized))
    checks.append(check_required_terms("must_use", expected.get("must_use"), normalized.full_text))
    checks.append(check_absent_terms("avoid", expected.get("avoid"), normalized.plan_text))
    checks.append(
        check_required_terms(
            "must_include_types",
            expected.get("must_include_types"),
            normalized.plan_text,
        )
    )
    checks.append(
        check_required_terms(
            "preferences",
            expected.get("preferences"),
            normalized.full_text,
            required_ratio=0.5,
        )
    )
    checks.append(check_time_limit(expected, normalized.full_text))
    checks.append(
        check_absent_terms(
            "should_avoid_recent_dishes",
            expected.get("should_avoid_recent_dishes"),
            normalized.plan_text,
        )
    )
    checks.append(check_memory_terms("memory_should_use", expected, normalized.memory_text))
    checks.append(check_memory_terms("memory_should_conflict", expected, normalized.conflict_text))
    checks.append(check_report_sections(expected, normalized.menu_markdown))
    checks.append(check_shopping_list_dedupe(expected, normalized.shopping_list))

    applicable = [check for check in checks if check.weight > 0]
    total_weight = sum(check.weight for check in applicable)
    score = (
        sum(check.score * check.weight for check in applicable) / total_weight
        if total_weight
        else 1.0
    )

    return EvalResult(
        case_id=str(case.get("id") or "unknown"),
        category=str(case.get("category") or "uncategorized"),
        passed=score >= 0.8 and all(check.passed for check in applicable if check.name in HARD_CHECKS),
        score=score,
        checks=checks,
    )


HARD_CHECKS = {
    "required_outputs",
    "dish_count",
    "avoid",
}


@dataclass(frozen=True)
class NormalizedOutput:
    raw: dict[str, Any]
    dish_list: list[dict[str, Any]]
    shopping_list: list[str]
    menu_markdown: str
    full_text: str
    plan_text: str
    memory_text: str
    conflict_text: str


def normalize_output(output: Any) -> NormalizedOutput:
    """Convert API responses, dataclasses, and dict-like outputs into one shape."""
    raw = to_plain_data(output)
    if not isinstance(raw, dict):
        raw = {}

    dish_list = raw.get("dish_list") or raw.get("tasks") or []
    if not isinstance(dish_list, list):
        dish_list = []
    normalized_dishes = [item for item in (to_plain_data(dish) for dish in dish_list) if isinstance(item, dict)]

    shopping_list = raw.get("shopping_list") or []
    if not isinstance(shopping_list, list):
        shopping_list = [str(shopping_list)] if shopping_list else []
    normalized_shopping = [str(item) for item in shopping_list if str(item).strip()]

    menu_markdown = str(raw.get("menu_markdown") or raw.get("report") or "")

    dish_text_parts: list[str] = []
    memory_parts: list[str] = []
    conflict_parts: list[str] = []
    for dish in normalized_dishes:
        dish_text_parts.append(flatten_text(dish))
        memory_parts.extend(str(item) for item in dish.get("memory_used") or [])
        conflict_parts.extend(str(item) for item in dish.get("memory_conflicts") or [])

    plan_text = "\n".join(dish_text_parts + normalized_shopping)
    full_text = "\n".join([plan_text, menu_markdown])

    return NormalizedOutput(
        raw=raw,
        dish_list=normalized_dishes,
        shopping_list=normalized_shopping,
        menu_markdown=menu_markdown,
        full_text=normalize_text(full_text),
        plan_text=normalize_text(plan_text),
        memory_text=normalize_text("\n".join(memory_parts)),
        conflict_text=normalize_text("\n".join(conflict_parts)),
    )


def check_required_outputs(expected: dict[str, Any], output: NormalizedOutput) -> CheckResult:
    required = expected.get("required_outputs") or []
    if not required:
        return skipped("required_outputs")

    missing: list[str] = []
    for name in required:
        if name == "dish_list" and not output.dish_list:
            missing.append(name)
        elif name == "shopping_list" and not output.shopping_list:
            missing.append(name)
        elif name == "menu_markdown" and not output.menu_markdown.strip():
            missing.append(name)

    return CheckResult(
        name="required_outputs",
        passed=not missing,
        score=1.0 if not missing else 0.0,
        weight=1.5,
        detail="" if not missing else "Missing: " + ", ".join(missing),
    )


def check_dish_count(expected: dict[str, Any], output: NormalizedOutput) -> CheckResult:
    count = len(output.dish_list)
    if "dish_count" in expected:
        target = int(expected["dish_count"])
        passed = count == target
        return CheckResult(
            name="dish_count",
            passed=passed,
            score=1.0 if passed else 0.0,
            weight=1.2,
            detail=f"Expected {target}, got {count}.",
        )

    min_count = expected.get("dish_count_min")
    max_count = expected.get("dish_count_max")
    if min_count is None and max_count is None:
        return skipped("dish_count")

    lower = int(min_count if min_count is not None else 0)
    upper = int(max_count if max_count is not None else 999)
    passed = lower <= count <= upper
    return CheckResult(
        name="dish_count",
        passed=passed,
        score=1.0 if passed else 0.0,
        weight=1.2,
        detail=f"Expected {lower}-{upper}, got {count}.",
    )


def check_required_terms(
    name: str,
    terms: Any,
    text: str,
    *,
    required_ratio: float = 1.0,
) -> CheckResult:
    term_list = as_string_list(terms)
    if not term_list:
        return skipped(name)

    found = [term for term in term_list if contains_term(text, term)]
    score = len(found) / len(term_list)
    passed = score >= required_ratio
    missing = [term for term in term_list if term not in found]

    return CheckResult(
        name=name,
        passed=passed,
        score=score,
        weight=1.0,
        detail="" if not missing else "Missing: " + ", ".join(missing),
    )


def check_absent_terms(name: str, terms: Any, text: str) -> CheckResult:
    term_list = as_string_list(terms)
    if not term_list:
        return skipped(name)

    present = [term for term in term_list if contains_term(text, term)]
    return CheckResult(
        name=name,
        passed=not present,
        score=1.0 if not present else 0.0,
        weight=1.3,
        detail="" if not present else "Present banned terms: " + ", ".join(present),
    )


def check_time_limit(expected: dict[str, Any], text: str) -> CheckResult:
    limit = expected.get("time_limit_minutes")
    if limit is None:
        return skipped("time_limit_minutes")

    numbers = [int(match) for match in re.findall(r"(\d+)\s*分钟", text)]
    within_limit = [value for value in numbers if value <= int(limit)]
    passed = bool(within_limit) or contains_term(text, "快手")

    return CheckResult(
        name="time_limit_minutes",
        passed=passed,
        score=1.0 if passed else 0.0,
        weight=0.8,
        detail=f"Expected <= {limit} minutes; found: {numbers or 'none'}.",
    )


def check_memory_terms(name: str, expected: dict[str, Any], text: str) -> CheckResult:
    terms = as_string_list(expected.get(name))
    if not terms:
        return skipped(name)
    return check_required_terms(name, terms, text, required_ratio=1.0)


def check_report_sections(expected: dict[str, Any], menu_markdown: str) -> CheckResult:
    sections = as_string_list(expected.get("report_sections"))
    if not sections:
        return skipped("report_sections")

    text = normalize_text(menu_markdown)
    found = [section for section in sections if contains_term(text, section)]
    score = len(found) / len(sections)
    missing = [section for section in sections if section not in found]

    return CheckResult(
        name="report_sections",
        passed=not missing,
        score=score,
        weight=1.0,
        detail="" if not missing else "Missing sections: " + ", ".join(missing),
    )


def check_shopping_list_dedupe(expected: dict[str, Any], shopping_list: list[str]) -> CheckResult:
    terms = as_string_list(expected.get("shopping_list_should_merge_or_dedupe"))
    if not terms:
        return skipped("shopping_list_should_merge_or_dedupe")

    failures = []
    for term in terms:
        matches = [item for item in shopping_list if contains_term(item, term)]
        if len(matches) > 1:
            failures.append(f"{term} appears {len(matches)} times")

    return CheckResult(
        name="shopping_list_should_merge_or_dedupe",
        passed=not failures,
        score=1.0 if not failures else 0.0,
        weight=0.8,
        detail="; ".join(failures),
    )


def summarize_results(results: Iterable[EvalResult]) -> dict[str, Any]:
    """Build a compact summary for console output or report JSON."""
    result_list = list(results)
    if not result_list:
        return {"total": 0, "passed": 0, "average_score": 0.0, "by_category": {}}

    by_category: dict[str, dict[str, Any]] = {}
    for result in result_list:
        bucket = by_category.setdefault(
            result.category,
            {"total": 0, "passed": 0, "average_score": 0.0, "scores": []},
        )
        bucket["total"] += 1
        bucket["passed"] += int(result.passed)
        bucket["scores"].append(result.score)

    for bucket in by_category.values():
        scores = bucket.pop("scores")
        bucket["average_score"] = round(sum(scores) / len(scores), 4)

    return {
        "total": len(result_list),
        "passed": sum(1 for result in result_list if result.passed),
        "average_score": round(sum(result.score for result in result_list) / len(result_list), 4),
        "by_category": by_category,
    }


def skipped(name: str) -> CheckResult:
    return CheckResult(name=name, passed=True, score=1.0, weight=0.0, detail="Skipped.")


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


def flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(flatten_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text)).lower()


def contains_term(text: str, term: str) -> bool:
    return normalize_text(term) in normalize_text(text)


if __name__ == "__main__":
    loaded_cases = load_cases()
    print(json.dumps({"cases": len(loaded_cases)}, ensure_ascii=False, indent=2))
