"""Safe evaluation of structured condition rules (no code execution)."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Tuple

from app.core.errors import ErrorCategory, NodeExecutionError
from app.schemas.conditions import UNARY_OPERATORS, ConditionGroup, ConditionRule

MAX_REGEX_PATTERN = 512
MAX_REGEX_INPUT = 100_000


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None


def _equals(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        lb, rb = _as_bool(left), _as_bool(right)
        return lb is not None and rb is not None and lb == rb
    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None and not (isinstance(left, str) and isinstance(right, str)):
        return ln == rn
    return left == right


def _compare(left: Any, right: Any, op: str, field: str) -> bool:
    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None:
        a, b = ln, rn
    elif isinstance(left, str) and isinstance(right, str):
        a, b = left, right  # type: ignore[assignment]
    else:
        raise NodeExecutionError(
            ErrorCategory.NODE_EXECUTION,
            f"Cannot compare {type(left).__name__} with {type(right).__name__} using '{op}'.",
            field=field,
            suggestion="Compare numbers with numbers (or strings with strings).",
            details={"left": repr(left)[:200], "right": repr(right)[:200]},
        )
    return {"gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, (list, dict, tuple, set)) and len(value) == 0)


def evaluate_rule(left: Any, operator: str, right: Any, field: str = "conditions") -> bool:
    if operator == "eq":
        return _equals(left, right)
    if operator == "neq":
        return not _equals(left, right)
    if operator in {"gt", "gte", "lt", "lte"}:
        return _compare(left, right, operator, field)
    if operator in {"contains", "not_contains"}:
        if isinstance(left, str):
            result = str(right) in left
        elif isinstance(left, (list, tuple)):
            result = right in left
        elif isinstance(left, dict):
            result = str(right) in left
        elif left is None:
            result = False
        else:
            result = str(right) in str(left)
        return result if operator == "contains" else not result
    if operator == "starts_with":
        return isinstance(left, str) and left.startswith(str(right))
    if operator == "ends_with":
        return isinstance(left, str) and left.endswith(str(right))
    if operator == "is_empty":
        return _is_empty(left)
    if operator == "not_empty":
        return not _is_empty(left)
    if operator == "is_true":
        return _as_bool(left) is True
    if operator == "is_false":
        return _as_bool(left) is False
    if operator == "regex":
        pattern = str(right or "")
        if len(pattern) > MAX_REGEX_PATTERN:
            raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION,
                                     f"Regex pattern exceeds {MAX_REGEX_PATTERN} characters.", field=field)
        text = "" if left is None else str(left)
        if len(text) > MAX_REGEX_INPUT:
            raise NodeExecutionError(ErrorCategory.NODE_EXECUTION,
                                     f"Regex input exceeds {MAX_REGEX_INPUT} characters.", field=field)
        try:
            return re.search(pattern, text) is not None
        except re.error as exc:
            raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, f"Invalid regex: {exc}", field=field) from exc
    raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, f"Unknown operator '{operator}'.", field=field)


Resolver = Callable[[Any, str], Any]


def evaluate_group(group: ConditionGroup, resolve: Resolver,
                   field: str = "conditions") -> Tuple[bool, List[Dict[str, Any]]]:
    """Evaluate a rule group. ``resolve(value, field_path)`` resolves operands."""
    details: List[Dict[str, Any]] = []
    results: List[bool] = []
    for idx, rule in enumerate(group.rules):
        rule_field = f"{field}.rules[{idx}]"
        left = resolve(rule.left, f"{rule_field}.left")
        right = None if rule.operator in UNARY_OPERATORS else resolve(rule.right, f"{rule_field}.right")
        passed = evaluate_rule(left, rule.operator, right, rule_field)
        results.append(passed)
        details.append({"left": left, "operator": rule.operator, "right": right, "result": passed})
    outcome = all(results) if group.combinator == "all" else any(results)
    return outcome, details


def identity_resolver(value: Any, _field: str) -> Any:
    return value


__all__ = ["evaluate_group", "evaluate_rule", "identity_resolver", "ConditionGroup", "ConditionRule"]
