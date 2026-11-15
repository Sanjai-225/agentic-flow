"""Executors for Milestone 2 trigger, flow-control and data nodes.

Triggers (Form Submission, Schedule) receive their payload from the ingress that created the execution
(public form endpoint / scheduler) as ``ctx.upstream``. A manual test run of such a workflow gets the same
output *shape*, clearly marked ``test_run: true``, so downstream references work in the editor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.conditions import evaluate_group
from app.engine.contracts import ExecutionContext, NodeExecutionResult, NodeExecutor
from app.executors import register
from app.registry.configs import (
    ArrayConfig,
    DateTimeConfig,
    FormTriggerConfig,
    LoopConfig,
    MergeConfig,
    ScheduleTriggerConfig,
    SwitchConfig,
)


# --------------------------------------------------------------------------------------------- triggers
@register
class FormTriggerExecutor(NodeExecutor):
    operation_id = "core.form_trigger"
    config_model = FormTriggerConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        payload = ctx.upstream if isinstance(ctx.upstream, dict) else {}
        if "submission" not in payload:  # manual test run from the editor
            payload = {"submission": payload, "submitted_at": datetime.now(UTC).isoformat(),
                       "form_id": None, "test_run": True}
        ctx.logger.info("Form submission received", {"fields": sorted(payload.get("submission") or {})})
        return NodeExecutionResult(output=payload)


@register
class ScheduleTriggerExecutor(NodeExecutor):
    operation_id = "core.schedule_trigger"
    config_model = ScheduleTriggerConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, ScheduleTriggerConfig)
        payload = ctx.upstream if isinstance(ctx.upstream, dict) else {}
        if "scheduled_for" not in payload:  # manual test run from the editor
            now = datetime.now(UTC).isoformat()
            payload = {"schedule_id": None, "scheduled_for": now, "fired_at": now, "timezone": config.timezone,
                       "workflow_id": ctx.workflow_id, "catch_up": False, "test_run": True, **payload}
        ctx.logger.info("Schedule fired", {"scheduled_for": payload.get("scheduled_for"),
                                           "timezone": payload.get("timezone")})
        return NodeExecutionResult(output=payload)


# --------------------------------------------------------------------------------------------- Switch
@register
class SwitchExecutor(NodeExecutor):
    """Evaluates each case's rules (already resolved by the engine) and routes to the matching port(s)."""

    operation_id = "core.switch"
    config_model = SwitchConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, SwitchConfig)
        if ctx.resolve is None:
            raise NodeExecutionError(ErrorCategory.ENGINE_ERROR, "Resolver unavailable for Switch cases.")
        matched: List[str] = []
        evaluations: List[Dict[str, Any]] = []
        for index, case in enumerate(config.cases):
            def _resolve(value: Any, field: str, _i: int = index) -> Any:
                assert ctx.resolve is not None
                return ctx.resolve(value, f"cases[{_i}].{field}", None)

            outcome, details = evaluate_group(case.conditions, _resolve)
            evaluations.append({"case": case.key, "matched": outcome, "rules": details})
            if outcome:
                matched.append(case.key)
                if config.mode == "first":
                    break
        route = matched or ["default"]
        ctx.logger.info(f"Switch routed to {', '.join(route)}", {"evaluations": evaluations})
        return NodeExecutionResult(output=ctx.upstream, route=route,
                                   metadata={"selected": route, "evaluations": evaluations})


# --------------------------------------------------------------------------------------------- Merge
@register
class MergeExecutor(NodeExecutor):
    """Combines the outputs that reached ``input_1..input_N``.

    Semantics are *sequential synchronisation*, not parallelism: the engine runs nodes one at a time in
    topological order, so by the time Merge runs every predecessor has already finished or been skipped.
    Merge runs exactly once per execution.
    """

    operation_id = "core.merge"
    config_model = MergeConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, MergeConfig)
        ports = [f"input_{i}" for i in range(1, config.inputs + 1)]
        arrived: Dict[str, Any] = {}
        for port in ports:
            entries = ctx.inputs_by_port.get(port) or []
            if entries:
                arrived[port] = entries[0]["output"] if len(entries) == 1 else [e["output"] for e in entries]
        missing = [p for p in ports if p not in arrived]
        if missing and config.require == "all":
            raise NodeExecutionError(
                ErrorCategory.MISSING_INPUT,
                f"Merge input(s) {', '.join(missing)} were not reached: the branch connected to them was skipped "
                "or did not run.",
                suggestion="Set 'require' to 'any' to merge whatever arrived, or make sure every connected branch "
                           "runs.", details={"missing": missing, "received": sorted(arrived)})
        if config.mode == "by_input":
            output: Any = {p: arrived.get(p) for p in ports}
        elif config.mode == "append":
            items: List[Any] = []
            for p in ports:
                if p in arrived:
                    value = arrived[p]
                    items.extend(value if isinstance(value, list) else [value])
            output = {"items": items, "count": len(items)}
        else:
            merged: Dict[str, Any] = {}
            for p in ports:
                if p not in arrived:
                    continue
                if not isinstance(arrived[p], dict):
                    kind = type(arrived[p]).__name__
                    raise NodeExecutionError(ErrorCategory.NODE_EXECUTION,
                                             f"merge_objects needs objects, but {p} received {kind}.", field="mode")
                merged.update(arrived[p])
            output = merged
        ctx.logger.info(f"Merged {len(arrived)} of {len(ports)} input(s)", {"received": sorted(arrived)})
        return NodeExecutionResult(output=output, metadata={"received": sorted(arrived), "missing": missing})


# --------------------------------------------------------------------------------------------- Loop
@register
class LoopExecutor(NodeExecutor):
    """Validates the array; the engine then runs the nodes on the 'item' port once per element and routes
    the collected results to the 'done' port (see ``WorkflowRunner._run_loop``)."""

    operation_id = "core.loop"
    config_model = LoopConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, LoopConfig)
        items = config.items
        if not isinstance(items, list):
            raise NodeExecutionError(ErrorCategory.NODE_EXECUTION,
                                     f"Loop 'items' must resolve to an array, got {type(items).__name__}.",
                                     field="items",
                                     suggestion="Point 'items' at an array, e.g. {{trigger.records}}.")
        limit = min(config.max_items, get_settings().LOOP_MAX_ITEMS)
        if len(items) > limit:
            raise NodeExecutionError(ErrorCategory.ITERATION_LIMIT,
                                     f"The array has {len(items)} items, more than the loop limit of {limit}.",
                                     field="max_items", details={"count": len(items), "limit": limit})
        return NodeExecutionResult(output={"items": items, "count": len(items)}, route=[],
                                   metadata={"loop": True, "count": len(items)})


# --------------------------------------------------------------------------------------------- Date & Time
def _as_datetime(value: Any, tz: ZoneInfo, field: str) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=UTC).astimezone(tz)
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NodeExecutionError(ErrorCategory.NODE_EXECUTION,
                                 f"'{field}' is not an ISO-8601 date/time or Unix timestamp: {text[:60]!r}.",
                                 field=field) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


_UNIT_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}


@register
class DateTimeExecutor(NodeExecutor):
    operation_id = "core.datetime"
    config_model = DateTimeConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, DateTimeConfig)
        tz = ZoneInfo(config.timezone)
        op = config.operation
        if op == "now":
            moment = datetime.now(UTC).astimezone(tz)
            return NodeExecutionResult(output={"result": moment.isoformat(), "timestamp": moment.timestamp(),
                                               "timezone": config.timezone})
        value = _as_datetime(config.value, tz, "value")
        if op == "format":
            try:
                text = value.astimezone(tz).strftime(config.format or "%Y-%m-%d %H:%M:%S %Z")
            except ValueError as exc:
                raise NodeExecutionError(ErrorCategory.NODE_EXECUTION, f"Invalid format: {exc}",
                                         field="format") from exc
            return NodeExecutionResult(output={"result": text})
        if op == "parse":
            local = value.astimezone(tz)
            return NodeExecutionResult(output={"result": local.isoformat(), "year": local.year, "month": local.month,
                                               "day": local.day, "hour": local.hour, "minute": local.minute,
                                               "weekday": local.strftime("%A"), "timestamp": local.timestamp()})
        if op in ("add", "subtract"):
            amount = float(config.amount or 0) * (1 if op == "add" else -1)
            result = (value + timedelta(seconds=amount * _UNIT_SECONDS[config.unit])).astimezone(tz)
            return NodeExecutionResult(output={"result": result.isoformat(), "timestamp": result.timestamp()})
        if op == "diff":
            other = _as_datetime(config.other, tz, "other")
            diff = (other - value).total_seconds() / _UNIT_SECONDS[config.unit]
            return NodeExecutionResult(output={"result": round(diff, 6), "unit": config.unit})
        local = value.astimezone(tz)
        if config.start_of == "hour":
            start = local.replace(minute=0, second=0, microsecond=0)
        elif config.start_of == "day":
            start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        elif config.start_of == "week":
            start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return NodeExecutionResult(output={"result": start.isoformat(), "timestamp": start.timestamp()})


# --------------------------------------------------------------------------------------------- Array
def _pick(item: Any, path: Optional[str]) -> Any:
    if not path:
        return item
    current = item
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _not_a_number(index: int, field: Optional[str], value: Any) -> NodeExecutionError:
    where = f"Item {index}" + (f" field '{field}'" if field else "")
    return NodeExecutionError(ErrorCategory.NODE_EXECUTION, f"{where} is not a number ({value!r}).", field="field")


def _numeric(values: List[Any], field: Optional[str]) -> List[float]:
    out = []
    for i, v in enumerate(values):
        if isinstance(v, bool) or v is None:
            raise _not_a_number(i, field, v)
        try:
            out.append(float(v))
        except (TypeError, ValueError) as exc:
            raise _not_a_number(i, field, v) from exc
    return out


def _tidy(value: float) -> Any:
    return int(value) if float(value).is_integer() else value


@register
class ArrayExecutor(NodeExecutor):
    operation_id = "core.array"
    config_model = ArrayConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, ArrayConfig)
        items = config.items
        if not isinstance(items, list):
            raise NodeExecutionError(ErrorCategory.NODE_EXECUTION,
                                     f"'items' must resolve to an array, got {type(items).__name__}.", field="items")
        op, field = config.operation, config.field
        result: Any
        if op == "count":
            result = len(items)
        elif op == "reverse":
            result = list(reversed(items))
        elif op == "limit":
            result = items[: config.limit]
        elif op == "pluck":
            result = [_pick(i, field) for i in items]
        elif op == "flatten":
            result = [x for i in items for x in (i if isinstance(i, list) else [i])]
        elif op == "chunk":
            size = int(config.size or 1)
            result = [items[i:i + size] for i in range(0, len(items), size)]
        elif op == "unique":
            seen: set[str] = set()
            result = []
            for i in items:
                marker = json.dumps(_pick(i, field), sort_keys=True, default=str)
                if marker not in seen:
                    seen.add(marker)
                    result.append(i)
        elif op == "sort":
            keyed = [(_pick(i, field), i) for i in items]
            present = [k for k in keyed if k[0] is not None]
            absent = [k for k in keyed if k[0] is None]
            try:
                present.sort(key=lambda k: k[0], reverse=config.order == "desc")
            except TypeError as exc:
                raise NodeExecutionError(ErrorCategory.NODE_EXECUTION,
                                         "Items have mixed types and cannot be sorted together.",
                                         field="field") from exc
            result = [i for _, i in present + absent]
        else:
            values = _numeric([_pick(i, field) for i in items], field)
            if not values and op != "sum":
                raise NodeExecutionError(ErrorCategory.NODE_EXECUTION, f"Cannot compute {op} of an empty array.",
                                         field="items")
            if op == "sum":
                result = _tidy(sum(values))
            elif op == "avg":
                result = _tidy(sum(values) / len(values))
            elif op == "min":
                result = _tidy(min(values))
            else:
                result = _tidy(max(values))
        count = len(result) if isinstance(result, list) else len(items)
        return NodeExecutionResult(output={"result": result, "count": count})
