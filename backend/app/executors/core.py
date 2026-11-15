"""Deterministic core executors: triggers, data and control-flow nodes."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.conditions import evaluate_group, identity_resolver
from app.engine.contracts import ExecutionContext, NodeExecutionResult, NodeExecutor
from app.engine.expressions import to_text
from app.executors import register
from app.registry.configs import (
    EndConfig,
    FilterConfig,
    IfConfig,
    JsonParseConfig,
    ManualTriggerConfig,
    SetConfig,
    TransformConfig,
    WebhookTriggerConfig,
)


def set_path(target: Dict[str, Any], path: str, value: Any, field: str) -> None:
    """Assign ``value`` at a dot path, creating nested objects."""
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, "Field name must not be empty.", field=field)
    cursor = target
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if nxt is None:
            nxt = {}
            cursor[part] = nxt
        elif not isinstance(nxt, dict):
            raise NodeExecutionError(
                ErrorCategory.NODE_EXECUTION,
                f"Cannot set '{path}': '{part}' already holds a non-object value.",
                field=field,
            )
        cursor = nxt
    cursor[parts[-1]] = value


def describe_value(value: Any) -> str:
    """Short, user-facing description of a runtime value for error messages."""
    if value is None:
        return "empty (null)"
    if isinstance(value, bool):
        return f"the boolean {'true' if value else 'false'}"
    if isinstance(value, (int, float)):
        return f"the number {value}"
    if isinstance(value, str):
        if not value.strip():
            return "empty text"
        preview = value if len(value) <= 40 else value[:37] + "..."
        return f"the text '{preview}'"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return f"an array ({len(value)} items)"
    return f"a {type(value).__name__} value"


_TYPE_HINTS = {
    "number": "a number such as 42 or 3.5 (text like '42' is converted automatically)",
    "boolean": "true/false (also accepted: yes/no, 1/0)",
    "object": "a JSON object such as {\"key\": \"value\"}",
    "array": "a JSON array such as [1, 2, 3]",
}


def coerce(value: Any, type_: str, field: str, name: Optional[str] = None) -> Any:
    """Convert ``value`` to the Set field type, raising user-readable errors."""
    if type_ == "auto":
        return value
    label = f"Field '{name}'" if name else "The value"

    def fail(reason: str) -> NodeExecutionError:
        return NodeExecutionError(
            ErrorCategory.NODE_EXECUTION,
            f"{label} expects {_TYPE_HINTS.get(type_, type_)}, but the value is {reason}.",
            field=field,
            suggestion=f"Check the value or the upstream data it references, or change the field type "
                       f"from '{type_}' to 'auto' to keep the value as it is.",
            details={"field_name": name, "expected_type": type_, "actual": describe_value(value)},
        )

    if type_ == "string":
        return to_text(value)
    if type_ == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise fail(describe_value(value))
        if isinstance(value, (int, float)):
            return value
        text = value.strip()
        try:
            number = float(text)
        except ValueError:
            raise fail(describe_value(value)) from None
        if number != number or number in (float("inf"), float("-inf")):
            raise fail(describe_value(value))
        return int(number) if number.is_integer() and "." not in text and "e" not in text.lower() else number
    if type_ == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no", ""}:
            return False
        raise fail(describe_value(value))
    if type_ in {"object", "array"}:
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise fail(f"text that is not valid JSON ({exc.msg} at column {exc.colno})") from None
        expected = dict if type_ == "object" else list
        if not isinstance(parsed, expected):
            raise fail(describe_value(parsed))
        return parsed
    return value


@register
class ManualTriggerExecutor(NodeExecutor):
    operation_id = "core.manual_trigger"
    config_model = ManualTriggerConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        payload = ctx.upstream if ctx.upstream is not None else {}
        ctx.logger.info("Manual trigger fired", {"payload_keys": sorted(payload) if isinstance(payload, dict) else None})
        return NodeExecutionResult(output=payload)


@register
class WebhookTriggerExecutor(NodeExecutor):
    operation_id = "core.webhook_trigger"
    config_model = WebhookTriggerConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        payload = ctx.upstream if ctx.upstream is not None else {}
        ctx.logger.info("Webhook trigger fired")
        return NodeExecutionResult(output=payload)


@register
class SetExecutor(NodeExecutor):
    operation_id = "core.set"
    config_model = SetConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, SetConfig)
        result: Dict[str, Any] = {}
        if config.keep_input:
            if isinstance(ctx.upstream, dict):
                result = copy.deepcopy(ctx.upstream)
            elif ctx.upstream is not None:
                result = {"input": copy.deepcopy(ctx.upstream)}
        for idx, f in enumerate(config.fields):
            field = f"fields[{idx}].value"
            set_path(result, f.name, coerce(f.value, f.type, field, f.name), f"fields[{idx}].name")
        return NodeExecutionResult(output=result)


@register
class JsonParseExecutor(NodeExecutor):
    operation_id = "core.json_parse"
    config_model = JsonParseConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, JsonParseConfig)
        source = config.source
        if isinstance(source, (dict, list)):
            ctx.logger.info("Source is already structured JSON; passing it through unchanged.")
            return NodeExecutionResult(output=source)
        if not isinstance(source, str):
            raise NodeExecutionError(
                ErrorCategory.NODE_EXECUTION,
                f"JSON Parse expects text, got {type(source).__name__}.",
                field="source",
            )
        try:
            return NodeExecutionResult(output=json.loads(source))
        except json.JSONDecodeError as exc:
            raise NodeExecutionError(
                ErrorCategory.NODE_EXECUTION,
                f"Source is not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.",
                field="source",
                suggestion="Check that the referenced value is a JSON string.",
                details={"preview": source[:300]},
            ) from exc


@register
class FilterExecutor(NodeExecutor):
    operation_id = "core.filter"
    config_model = FilterConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, FilterConfig)
        items = config.items
        if not isinstance(items, list):
            raise NodeExecutionError(
                ErrorCategory.NODE_EXECUTION,
                f"Filter 'items' must resolve to an array, got {type(items).__name__}.",
                field="items",
                suggestion="Point 'items' at an array, e.g. {{nodes.http_1.output.body.items}}.",
            )
        if ctx.resolve is None:
            raise NodeExecutionError(ErrorCategory.ENGINE_ERROR, "Resolver unavailable for Filter rules.")
        kept = []
        for item in items:
            def _resolve(value: Any, field: str, _item: Any = item) -> Any:
                assert ctx.resolve is not None
                return ctx.resolve(value, field, {"item": _item})

            passed, _ = evaluate_group(config.conditions, _resolve)
            if passed:
                kept.append(item)
        return NodeExecutionResult(
            output={"items": kept, "kept": len(kept), "dropped": len(items) - len(kept)},
        )


@register
class TransformExecutor(NodeExecutor):
    operation_id = "core.transform"
    config_model = TransformConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, TransformConfig)
        result: Dict[str, Any] = {}
        for target, value in config.mappings.items():
            set_path(result, target, value, f"mappings.{target}")
        return NodeExecutionResult(output=result)


@register
class IfExecutor(NodeExecutor):
    operation_id = "core.if"
    config_model = IfConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, IfConfig)
        outcome, details = evaluate_group(config.conditions, identity_resolver)
        branch = "true" if outcome else "false"
        ctx.logger.info(f"Condition evaluated to {outcome}; following '{branch}' branch", {"rules": details})
        # Pass upstream data through unchanged so the selected branch can use {{input...}}.
        return NodeExecutionResult(
            output=ctx.upstream,
            route=[branch],
            metadata={"result": outcome, "rules": details},
        )


@register
class EndExecutor(NodeExecutor):
    operation_id = "core.end"
    config_model = EndConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, EndConfig)
        output = config.output if config.output is not None else ctx.upstream
        return NodeExecutionResult(output=output, route=[])
