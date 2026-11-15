"""Trigger and flow-control node definitions added in Milestone 2."""

from typing import Any, Dict, List

from app.registry.configs import FormTriggerConfig, ScheduleTriggerConfig
from app.registry.output_hooks import path_segment
from app.schemas.registry import (
    ConfigField,
    NodeCategory,
    NodeDefinition,
    PortDataType,
    PortDefinition,
    PortType,
)


def _out(id_: str, name: str) -> PortDefinition:
    return PortDefinition(id=id_, name=name, port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT)


def _in(id_: str, name: str) -> PortDefinition:
    return PortDefinition(id=id_, name=name, port_type=PortType.INPUT, data_type=PortDataType.ANY)


def infer_form(config: Dict[str, Any]) -> List[str]:
    paths = [".submission"]
    for field in config.get("fields") or []:
        if isinstance(field, dict) and field.get("key"):
            paths.append(".submission" + path_segment(str(field["key"])))
    return paths + [".submitted_at", ".form_id"]


def infer_schedule(config: Dict[str, Any]) -> List[str]:
    return [".scheduled_for", ".fired_at", ".timezone", ".schedule_id", ".workflow_id", ".catch_up"]


def trigger_definitions() -> List[NodeDefinition]:
    return [
        NodeDefinition(
            operation_id="core.form_trigger",
            node_type="form_trigger",
            label="Form Submission Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Publishes a hosted form at a secret public URL. Each valid submission (validated on the "
                        "server) starts the workflow with the submitted fields.",
            inputs=[],
            outputs=[_out("out_submission", "Submission")],
            default_config={"title": "Contact us", "description": "",
                            "fields": [{"key": "name", "label": "Name", "type": "text", "required": True},
                                       {"key": "email", "label": "Email", "type": "email", "required": True}],
                            "submit_label": "Submit", "success_message": "Thank you! Your response has been received."},
            icon="form",
            tags=["trigger", "form", "public", "submission", "input"],
            executable=True,
            status="ready",
            is_trigger=True,
            ports_in=[],
            ports_out=["main"],
            config_model=FormTriggerConfig,
            id_prefix="form_trigger",
            infer_output=infer_form,
            ai_guidance="Output: {{trigger.submission.<field_key>}} for each configured field (typed: numbers "
                        "are numbers, checkboxes booleans), plus {{trigger.submitted_at}}.",
            ui_fields=[
                ConfigField(key="title", label="Form title", widget="text", required=True),
                ConfigField(key="description", label="Description", widget="textarea"),
                ConfigField(key="fields", label="Fields", widget="form_fields", required=True),
                ConfigField(key="submit_label", label="Submit button label", widget="text"),
                ConfigField(key="success_message", label="Success message", widget="textarea"),
            ],
            output_schema={"type": "object", "properties": {
                "submission": {"type": "object"}, "submitted_at": {"type": "string"}, "form_id": {"type": "string"}}},
        ),
        NodeDefinition(
            operation_id="core.schedule_trigger",
            node_type="schedule",
            label="Schedule Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Starts the workflow on a schedule (every N minutes, hourly, daily, weekly, weekdays or "
                        "cron) in a chosen time zone. The backend scheduler persists schedules across restarts "
                        "and never runs the same occurrence twice.",
            inputs=[],
            outputs=[_out("out_schedule", "Schedule info")],
            default_config={"mode": "daily", "hour": 9, "minute": 0, "timezone": "UTC", "enabled": True,
                            "misfire_policy": "skip"},
            icon="clock",
            tags=["trigger", "schedule", "cron", "timer", "interval", "recurring"],
            executable=True,
            status="ready",
            is_trigger=True,
            ports_in=[],
            ports_out=["main"],
            config_model=ScheduleTriggerConfig,
            id_prefix="schedule_trigger",
            infer_output=infer_schedule,
            ai_guidance="Config: mode interval (interval_minutes) | hourly (minute) | daily/weekdays (hour, minute) "
                        "| weekly (weekdays list mon..sun, hour, minute) | cron (5-field cron). Always set an IANA "
                        "timezone. Output: {{trigger.scheduled_for}} (ISO time).",
            ui_fields=[
                ConfigField(key="mode", label="Schedule", widget="schedule", required=True,
                            help="The schedule is saved with the workflow and runs while the workflow is active."),
            ],
            output_schema={"type": "object", "properties": {
                "scheduled_for": {"type": "string"}, "fired_at": {"type": "string"}, "timezone": {"type": "string"},
                "schedule_id": {"type": "string"}, "workflow_id": {"type": "string"}, "catch_up": {"type": "boolean"}}},
        ),
    ]


def infer_merge(config: Dict[str, Any]) -> List[str]:
    mode = config.get("mode", "by_input")
    if mode == "append":
        return [".items", ".items[0]", ".count"]
    if mode == "merge_objects":
        return []
    try:
        count = max(2, min(5, int(config.get("inputs", 2))))
    except (TypeError, ValueError):
        count = 2
    return [f".input_{i}" for i in range(1, count + 1)]


def infer_loop(config: Dict[str, Any]) -> List[str]:
    return [".results", ".results[0]", ".count", ".succeeded", ".failed", ".errors", ".items"]


def infer_result(config: Dict[str, Any]) -> List[str]:
    return [".result", ".count"] if "items" in config else [".result", ".timestamp"]


def flow_control_definitions() -> List[NodeDefinition]:
    from app.registry.configs import ArrayConfig, DateTimeConfig, LoopConfig, MergeConfig, SwitchConfig
    from app.registry.output_hooks import infer_passthrough
    from app.schemas.registry import DynamicPorts
    from app.schemas.workflow import RetryPolicy

    rule = {"left": "{{input.status}}", "operator": "eq", "right": "paid"}
    return [
        NodeDefinition(
            operation_id="core.switch",
            node_type="switch_router",
            label="Switch",
            category=NodeCategory.LOGIC,
            description="Routes to one output per matching case (typed comparisons), or to 'default' when no case "
                        "matches. Passes the upstream data through unchanged.",
            inputs=[_in("in_val", "Input")],
            outputs=[_out("out_case", "Case outputs")],
            default_config={"mode": "first", "cases": [
                {"key": "case_1", "label": "Case 1", "conditions": {"combinator": "all", "rules": [rule]}}]},
            icon="route",
            tags=["logic", "switch", "router", "branch", "case"],
            executable=True,
            status="ready",
            ports_out=["default"],
            dynamic_ports=DynamicPorts(direction="out", source="list", config_key="cases", key_field="key",
                                       fixed=["default"]),
            config_model=SwitchConfig,
            # Cases are resolved one by one by the executor: with mode 'first', cases after the matching one are
            # never evaluated, so they may reference fields that this payload does not have.
            lazy_config_fields=["cases"],
            id_prefix="switch",
            infer_output=infer_passthrough,
            ai_guidance="Output ports are the case keys plus 'default'; connect edges with source_port set to a "
                        "case key or 'default'. mode 'first' takes the first matching case, 'all' every match.",
            ui_fields=[
                ConfigField(key="cases", label="Cases", widget="switch_cases", required=True,
                            supports_expressions=True,
                            help="Each case becomes an output port. Unmatched data goes to 'default'."),
                ConfigField(key="mode", label="Routing", widget="select", options=["first", "all"]),
            ],
            output_schema={"description": "Passes the upstream data through unchanged; the selected case is "
                                          "recorded in execution metadata."},
        ),
        NodeDefinition(
            operation_id="core.merge",
            node_type="merge_inputs",
            label="Merge",
            category=NodeCategory.DATA_PROCESSING,
            description="Combines the outputs of several branches into one object. Runs once, after every "
                        "connected branch has finished or been skipped (sequential synchronisation, not parallel "
                        "execution).",
            inputs=[_in("input_1", "Input 1"), _in("input_2", "Input 2")],
            outputs=[_out("out_merged", "Merged")],
            default_config={"inputs": 2, "mode": "by_input", "require": "all"},
            icon="merge",
            tags=["data", "merge", "combine", "join", "branches"],
            executable=True,
            status="ready",
            ports_in=["input_1", "input_2"],
            dynamic_ports=DynamicPorts(direction="in", source="count", config_key="inputs", prefix="input_",
                                       min_count=2, max_count=5),
            config_model=MergeConfig,
            id_prefix="merge",
            infer_output=infer_merge,
            ai_guidance="Input ports input_1..input_N (set target_port on incoming edges). mode by_input -> "
                        "{input_1: ..., input_2: ...}; append -> {items, count}; merge_objects -> one object. "
                        "require 'any' merges whatever arrived (e.g. after an If), 'all' fails when a branch "
                        "did not run.",
            ui_fields=[
                ConfigField(key="inputs", label="Number of inputs", widget="number"),
                ConfigField(key="mode", label="Combine as", widget="select",
                            options=["by_input", "append", "merge_objects"]),
                ConfigField(key="require", label="Inputs required", widget="select", options=["all", "any"],
                            help="'any' is needed when the inputs come from alternative branches (If/Switch)."),
            ],
            output_schema={"description": "by_input: {input_1, input_2, ...}; append: {items, count}; "
                                          "merge_objects: one merged object."},
        ),
        NodeDefinition(
            operation_id="core.loop",
            node_type="loop_items",
            label="Loop Over Items",
            category=NodeCategory.LOGIC,
            description="Runs the nodes connected to the 'item' output once for every element of an array "
                        "({{item}} and {{loop.index}} are available there), collects each iteration's result, "
                        "then continues on the 'done' output.",
            inputs=[_in("in_items", "Items")],
            outputs=[_out("item", "Each item"), _out("done", "Done")],
            default_config={"items": "", "max_items": 100, "on_item_error": "stop", "timeout_seconds": 300},
            icon="repeat",
            tags=["logic", "loop", "iterate", "for each", "items", "batch"],
            executable=True,
            status="ready",
            ports_out=["item", "done"],
            config_model=LoopConfig,
            id_prefix="loop",
            infer_output=infer_loop,
            default_retry=RetryPolicy(max_attempts=1),
            default_timeout_seconds=60,
            ai_guidance="Connect the loop body from source_port 'item' (body nodes use {{item.<field>}} and "
                        "{{loop.index}}; they must not connect to nodes outside the body) and the continuation "
                        "from source_port 'done'. After the loop read {{nodes.<loop_id>.output.results}} (one "
                        "entry per item: the output of the body's last node).",
            ui_fields=[
                ConfigField(key="items", label="Items (array)", widget="expression", required=True,
                            supports_expressions=True, placeholder="{{trigger.records}}"),
                ConfigField(key="max_items", label="Maximum items", widget="number"),
                ConfigField(key="on_item_error", label="When an item fails", widget="select",
                            options=["stop", "continue"]),
                ConfigField(key="timeout_seconds", label="Loop timeout (seconds)", widget="number"),
            ],
            output_schema={"type": "object", "properties": {
                "results": {"type": "array"}, "count": {"type": "integer"}, "succeeded": {"type": "integer"},
                "failed": {"type": "integer"}, "errors": {"type": "array"}, "items": {"type": "array"}}},
        ),
        NodeDefinition(
            operation_id="core.datetime",
            node_type="date_time",
            label="Date & Time",
            category=NodeCategory.DATA_PROCESSING,
            description="Current time, format, parse, add/subtract durations, difference between dates, or the "
                        "start of an hour/day/week/month, in any IANA time zone.",
            inputs=[_in("in_data", "Input")],
            outputs=[_out("out_result", "Result")],
            default_config={"operation": "now", "timezone": "UTC"},
            icon="calendar",
            tags=["data", "date", "time", "timezone", "format", "duration"],
            executable=True,
            status="ready",
            config_model=DateTimeConfig,
            id_prefix="datetime",
            infer_output=infer_result,
            ai_guidance="Read the value with {{nodes.<id>.output.result}}.",
            ui_fields=[
                ConfigField(key="operation", label="Operation", widget="select",
                            options=["now", "format", "parse", "add", "subtract", "diff", "start_of"]),
                ConfigField(key="value", label="Date/time", widget="expression", supports_expressions=True,
                            placeholder="{{trigger.created_at}}",
                            show_if={"operation": ["format", "parse", "add", "subtract", "diff", "start_of"]}),
                ConfigField(key="other", label="Second date/time", widget="expression", supports_expressions=True,
                            show_if={"operation": ["diff"]}),
                ConfigField(key="amount", label="Amount", widget="number", show_if={"operation": ["add", "subtract"]}),
                ConfigField(key="unit", label="Unit", widget="select",
                            options=["seconds", "minutes", "hours", "days", "weeks"],
                            show_if={"operation": ["add", "subtract", "diff"]}),
                ConfigField(key="start_of", label="Start of", widget="select", options=["hour", "day", "week", "month"],
                            show_if={"operation": ["start_of"]}),
                ConfigField(key="format", label="Format (strftime)", widget="text", placeholder="%Y-%m-%d",
                            show_if={"operation": ["format"]}),
                ConfigField(key="timezone", label="Time zone", widget="text", placeholder="Europe/Berlin"),
            ],
            output_schema={"type": "object", "properties": {"result": {}, "timestamp": {"type": "number"}}},
        ),
        NodeDefinition(
            operation_id="core.array",
            node_type="array_ops",
            label="Array Operations",
            category=NodeCategory.DATA_PROCESSING,
            description="Sort, limit, de-duplicate, pluck a field, sum/average/min/max/count, flatten, chunk or "
                        "reverse an array.",
            inputs=[_in("in_items", "Items")],
            outputs=[_out("out_result", "Result")],
            default_config={"items": "", "operation": "count"},
            icon="list",
            tags=["data", "array", "list", "sort", "aggregate", "sum", "unique"],
            executable=True,
            status="ready",
            config_model=ArrayConfig,
            id_prefix="array",
            infer_output=infer_result,
            ai_guidance="Read the value with {{nodes.<id>.output.result}}; 'field' is a dot path inside each item.",
            ui_fields=[
                ConfigField(key="items", label="Items (array)", widget="expression", required=True,
                            supports_expressions=True, placeholder="{{nodes.http_1.output.body.items}}"),
                ConfigField(key="operation", label="Operation", widget="select",
                            options=["sort", "limit", "unique", "pluck", "sum", "avg", "min", "max", "count",
                                     "flatten", "chunk", "reverse"]),
                ConfigField(key="field", label="Field (dot path)", widget="text", placeholder="price",
                            show_if={"operation": ["sort", "unique", "pluck", "sum", "avg", "min", "max"]}),
                ConfigField(key="order", label="Order", widget="select", options=["asc", "desc"],
                            show_if={"operation": ["sort"]}),
                ConfigField(key="limit", label="Limit", widget="number", show_if={"operation": ["limit"]}),
                ConfigField(key="size", label="Chunk size", widget="number", show_if={"operation": ["chunk"]}),
            ],
            output_schema={"type": "object", "properties": {"result": {}, "count": {"type": "integer"}}},
        ),
    ]


def flow_definitions() -> List[NodeDefinition]:
    return trigger_definitions() + flow_control_definitions()
