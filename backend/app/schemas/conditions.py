"""Structured, code-free condition rules used by If/Else and Filter nodes."""

from typing import Any, List, Literal

from pydantic import BaseModel, Field

ConditionOperator = Literal[
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "is_empty",
    "not_empty",
    "is_true",
    "is_false",
    "regex",
]

UNARY_OPERATORS = {"is_empty", "not_empty", "is_true", "is_false"}


class ConditionRule(BaseModel):
    left: Any = Field(default=None, description="Left operand: literal or {{...}} expression.")
    operator: ConditionOperator = "eq"
    right: Any = Field(default=None, description="Right operand (ignored for unary operators).")


class ConditionGroup(BaseModel):
    combinator: Literal["all", "any"] = "all"
    rules: List[ConditionRule] = Field(..., min_length=1)
