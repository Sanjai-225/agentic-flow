"""Unit tests for structured condition evaluation."""

import pytest

from app.core.errors import NodeExecutionError
from app.engine.conditions import evaluate_group, evaluate_rule, identity_resolver
from app.schemas.conditions import ConditionGroup


@pytest.mark.parametrize(
    "left,op,right,expected",
    [
        (5, "eq", 5, True),
        ("5", "eq", 5, True),
        ("abc", "eq", "abc", True),
        ("abc", "neq", "abd", True),
        (True, "eq", "true", True),
        (150, "gt", 100, True),
        ("150", "gt", 100, True),
        (100, "gte", 100, True),
        (99.5, "lt", 100, True),
        (100, "lte", 99, False),
        ("b", "gt", "a", True),
        ("hello world", "contains", "world", True),
        (["a", "b"], "contains", "b", True),
        ({"k": 1}, "contains", "k", True),
        ("hello", "not_contains", "z", True),
        (None, "contains", "z", False),
        ("prefix-x", "starts_with", "prefix", True),
        ("x.json", "ends_with", ".json", True),
        ("", "is_empty", None, True),
        ([], "is_empty", None, True),
        (None, "is_empty", None, True),
        ("x", "not_empty", None, True),
        (True, "is_true", None, True),
        ("false", "is_false", None, True),
        ("order-123", "regex", r"^order-\d+$", True),
    ],
)
def test_operators(left, op, right, expected):
    assert evaluate_rule(left, op, right) is expected


def test_incomparable_types_raise_clear_error():
    with pytest.raises(NodeExecutionError) as exc:
        evaluate_rule({"a": 1}, "gt", 3)
    assert "Cannot compare" in exc.value.error.message


def test_invalid_regex_is_schema_error():
    with pytest.raises(NodeExecutionError):
        evaluate_rule("x", "regex", "(")


def test_group_combinators():
    group_all = ConditionGroup(combinator="all", rules=[{"left": 1, "operator": "eq", "right": 1},
                                                        {"left": 1, "operator": "eq", "right": 2}])
    group_any = ConditionGroup(combinator="any", rules=group_all.rules)
    assert evaluate_group(group_all, identity_resolver)[0] is False
    assert evaluate_group(group_any, identity_resolver)[0] is True
    _, details = evaluate_group(group_any, identity_resolver)
    assert details[1] == {"left": 1, "operator": "eq", "right": 2, "result": False}
