"""Executable node definitions (Milestone 1).

Each definition here MUST have a matching executor registered in
``app.executors`` (enforced by tests). Legacy design types listed in
``node_type``/``aliases`` resolve to these operations, so existing AI-designer
output and older registry consumers keep working.
"""

from typing import List

from app.registry.examples import EXAMPLE_CONFIGS
from app.registry.output_hooks import (
    infer_end,
    infer_manual_trigger,
    infer_passthrough,
    infer_set,
    infer_transform,
)
from app.registry.configs import (
    EndConfig,
    FilterConfig,
    HttpRequestConfig,
    IfConfig,
    JsonParseConfig,
    ManualTriggerConfig,
    SetConfig,
    TransformConfig,
    WebhookTriggerConfig,
)
from app.schemas.registry import (
    ConfigField,
    NodeCategory,
    NodeDefinition,
    PortDataType,
    PortDefinition,
    PortType,
)
from app.schemas.workflow import RetryPolicy


def _in(id_: str, name: str, dt: PortDataType = PortDataType.ANY, desc: str = "") -> PortDefinition:
    return PortDefinition(id=id_, name=name, port_type=PortType.INPUT, data_type=dt, description=desc)


def _out(id_: str, name: str, dt: PortDataType = PortDataType.ANY, desc: str = "") -> PortDefinition:
    return PortDefinition(id=id_, name=name, port_type=PortType.OUTPUT, data_type=dt, description=desc)


def executable_definitions() -> List[NodeDefinition]:
    from app.registry.ai_nodes import ai_definitions
    from app.registry.flow_nodes import flow_definitions

    definitions = _executable_definitions() + ai_definitions() + flow_definitions()
    for d in definitions:
        d.example_config = EXAMPLE_CONFIGS.get(d.operation_id, d.default_config)
    return definitions


def _executable_definitions() -> List[NodeDefinition]:
    return [
        # ---------------- Triggers ----------------
        NodeDefinition(
            operation_id="core.manual_trigger",
            node_type="manual_trigger",
            aliases=["manual", "trigger", "manual_start", "start"],
            label="Manual Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Starts the workflow on demand from the editor or API. The run payload becomes its output.",
            inputs=[],
            outputs=[_out("out_payload", "Run Payload", PortDataType.OBJECT, "JSON payload supplied when the run starts")],
            default_config={"sample_payload": {}},
            icon="play",
            tags=["trigger", "manual", "start", "user_input"],
            executable=True,
            status="ready",
            is_trigger=True,
            ports_in=[],
            ports_out=["main"],
            config_model=ManualTriggerConfig,
            id_prefix="manual_trigger",
            infer_output=infer_manual_trigger,
            ui_fields=[
                ConfigField(key="sample_payload", label="Default run payload", widget="json",
                            help="Pre-filled JSON for the Run dialog."),
            ],
            output_schema={"type": "object", "description": "The JSON payload passed to the run."},
        ),
        NodeDefinition(
            operation_id="core.webhook_trigger",
            node_type="webhook_trigger",
            aliases=["webhook"],
            label="Webhook Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Starts the workflow when an HTTP request hits the workflow's secret webhook URL.",
            inputs=[],
            outputs=[
                _out("out_payload", "Payload", PortDataType.OBJECT, "Parsed request body"),
                _out("out_headers", "Headers", PortDataType.OBJECT, "Request headers (sensitive headers removed)"),
            ],
            default_config={"method": "POST"},
            icon="webhook",
            tags=["trigger", "webhook", "http", "api", "ingress"],
            executable=True,
            status="ready",
            is_trigger=True,
            ports_in=[],
            ports_out=["main"],
            config_model=WebhookTriggerConfig,
            id_prefix="webhook_trigger",
            ui_fields=[
                ConfigField(key="method", label="HTTP method", widget="select", options=["POST", "GET", "PUT"]),
            ],
            output_schema={
                "type": "object",
                "properties": {"body": {}, "headers": {"type": "object"}, "query": {"type": "object"},
                               "method": {"type": "string"}},
            },
        ),
        # ---------------- Data ----------------
        NodeDefinition(
            operation_id="core.set",
            node_type="set_variable",
            aliases=["set", "edit_fields", "set_fields", "assign"],
            label="Set Variable / Edit Fields",
            category=NodeCategory.DATA_PROCESSING,
            description="Creates or overwrites named fields using literals or references to upstream data.",
            inputs=[_in("in_data", "Input", PortDataType.OBJECT)],
            outputs=[_out("out_data", "Fields", PortDataType.OBJECT)],
            default_config={"fields": [], "keep_input": False},
            icon="pencil",
            tags=["data", "set", "variable", "fields", "assign"],
            executable=True,
            status="ready",
            config_model=SetConfig,
            id_prefix="set",
            infer_output=infer_set,
            ui_fields=[
                ConfigField(key="fields", label="Fields", widget="set_fields", supports_expressions=True),
                ConfigField(key="keep_input", label="Include upstream data", widget="boolean"),
            ],
            output_schema={"type": "object", "description": "Object containing the configured fields."},
        ),
        NodeDefinition(
            operation_id="core.json_parse",
            node_type="json_parse",
            aliases=["parse_json"],
            label="JSON Parse",
            category=NodeCategory.DATA_PROCESSING,
            description="Parses a JSON string into structured data.",
            inputs=[_in("in_text", "JSON Text", PortDataType.STRING)],
            outputs=[_out("out_data", "Parsed Data", PortDataType.ANY)],
            default_config={"source": ""},
            icon="braces",
            tags=["data", "json", "parse"],
            executable=True,
            status="ready",
            config_model=JsonParseConfig,
            id_prefix="json_parse",
            ui_fields=[
                ConfigField(key="source", label="JSON source", widget="expression", required=True,
                            supports_expressions=True, placeholder="{{nodes.http_1.output.body}}"),
            ],
            output_schema={"description": "The parsed JSON value (object, array or scalar)."},
        ),
        NodeDefinition(
            operation_id="core.filter",
            node_type="filter",
            aliases=["data_filter"],
            label="Filter",
            category=NodeCategory.DATA_PROCESSING,
            description="Keeps the items of an array that match structured rules.",
            inputs=[_in("in_items", "Item List", PortDataType.ARRAY, "Input array to filter")],
            outputs=[_out("out_passed", "Passed Items", PortDataType.ARRAY, "Items matching filter criteria")],
            default_config={
                "items": "",
                "conditions": {"combinator": "all", "rules": [{"left": "{{item.status}}", "operator": "eq", "right": ""}]},
            },
            icon="filter",
            tags=["data", "filter", "predicate", "clean"],
            executable=True,
            status="ready",
            config_model=FilterConfig,
            id_prefix="filter",
            lazy_config_fields=["conditions"],
            ui_fields=[
                ConfigField(key="items", label="Items (array)", widget="expression", required=True,
                            supports_expressions=True, placeholder="{{nodes.http_1.output.body.items}}"),
                ConfigField(key="conditions", label="Keep items where", widget="conditions",
                            supports_expressions=True, help="Use {{item.<field>}} to reference the current item."),
            ],
            output_schema={"type": "object", "properties": {"items": {"type": "array"}, "kept": {"type": "integer"},
                                                            "dropped": {"type": "integer"}}},
        ),
        NodeDefinition(
            operation_id="core.transform",
            node_type="data_transform",
            aliases=["transform", "mapper", "map_fields"],
            label="Transform / Map Fields",
            category=NodeCategory.DATA_PROCESSING,
            description="Builds a new object by mapping target fields to upstream values. Declarative, no code.",
            inputs=[_in("in_raw_data", "Raw Data", PortDataType.OBJECT, "Input structure to transform")],
            outputs=[_out("out_transformed", "Transformed Data", PortDataType.OBJECT, "Restructured output")],
            default_config={"mappings": {}},
            icon="shuffle",
            tags=["data", "transform", "mapping", "json", "format"],
            executable=True,
            status="ready",
            config_model=TransformConfig,
            id_prefix="transform",
            infer_output=infer_transform,
            ui_fields=[
                ConfigField(key="mappings", label="Mappings (target path → value)", widget="keyvalue_json",
                            supports_expressions=True,
                            help="Values may be JSON (objects, arrays, numbers) or references. A value that is "
                                 "exactly one {{reference}} keeps its original type."),
            ],
            output_schema={"type": "object"},
        ),
        # ---------------- Control flow ----------------
        NodeDefinition(
            operation_id="core.if",
            node_type="condition",
            aliases=["if", "if_else", "decision", "branch", "conditional"],
            label="If / Else",
            category=NodeCategory.LOGIC,
            description="Evaluates structured rules and routes execution to the 'true' or 'false' branch.",
            inputs=[_in("in_val", "Evaluation Input", PortDataType.ANY, "Value or object evaluated in condition")],
            outputs=[
                _out("out_true", "True (Yes)", PortDataType.ANY, "Fires when condition evaluates to true"),
                _out("out_false", "False (No)", PortDataType.ANY, "Fires when condition evaluates to false"),
            ],
            default_config={"conditions": {"combinator": "all", "rules": [{"left": "", "operator": "eq", "right": ""}]}},
            icon="git-branch",
            tags=["logic", "condition", "branch", "if", "decision"],
            executable=True,
            status="ready",
            ports_out=["true", "false"],
            config_model=IfConfig,
            id_prefix="if",
            infer_output=infer_passthrough,
            ui_fields=[
                ConfigField(key="conditions", label="Conditions", widget="conditions", supports_expressions=True),
            ],
            output_schema={"description": "Passes the upstream data through unchanged; the evaluation result "
                                          "is recorded in execution metadata and selects the branch."},
        ),
        NodeDefinition(
            operation_id="core.end",
            node_type="end",
            aliases=["finish", "stop", "terminate", "output", "end_node"],
            label="End",
            category=NodeCategory.LOGIC,
            description="Terminates a path and sets the workflow's final output.",
            inputs=[_in("in_data", "Final Data", PortDataType.ANY)],
            outputs=[],
            default_config={"output": None},
            icon="flag",
            tags=["logic", "end", "terminate", "output"],
            executable=True,
            status="ready",
            ports_out=[],
            config_model=EndConfig,
            id_prefix="end",
            infer_output=infer_end,
            ui_fields=[
                ConfigField(key="output", label="Final output", widget="json_template", supports_expressions=True,
                            help="Leave empty to return the upstream node's output. JSON with {{references}}: a "
                                 "value that is exactly one reference keeps its type (number, object, array)."),
            ],
            output_schema={"description": "The final workflow output."},
        ),
        # ---------------- HTTP ----------------
        NodeDefinition(
            operation_id="http.request",
            node_type="api_call",
            aliases=["http_request", "http", "api", "rest_api", "api_request"],
            label="HTTP Request",
            category=NodeCategory.TOOLS,
            description="Makes an HTTP request (GET, POST, PUT, PATCH, DELETE) to an external endpoint.",
            inputs=[_in("in_params", "Request Parameters", PortDataType.OBJECT, "Query params, body payload")],
            outputs=[
                _out("out_response", "Response Data", PortDataType.OBJECT, "Response body"),
                _out("out_status_code", "Status Code", PortDataType.NUMBER, "HTTP response status code"),
            ],
            default_config={"method": "GET", "url": "https://", "timeout_seconds": 30},
            icon="globe",
            tags=["tools", "api", "rest", "http", "fetch"],
            executable=True,
            status="ready",
            config_model=HttpRequestConfig,
            id_prefix="http",
            credentials=["http_bearer", "http_basic", "http_header"],
            side_effects=True,  # refined per request method by the executor
            idempotent=False,
            default_retry=RetryPolicy(max_attempts=1),
            default_timeout_seconds=120,
            ui_fields=[
                ConfigField(key="method", label="Method", widget="select",
                            options=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]),
                ConfigField(key="url", label="URL", widget="expression", required=True, supports_expressions=True,
                            placeholder="https://api.example.com/items"),
                ConfigField(key="query", label="Query parameters", widget="keyvalue", supports_expressions=True),
                ConfigField(key="headers", label="Headers", widget="keyvalue", supports_expressions=True),
                ConfigField(key="body_type", label="Body type", widget="select", options=["none", "json", "form", "raw"]),
                ConfigField(key="body", label="Body", widget="json_template", supports_expressions=True,
                            show_if={"body_type": ["json", "form", "raw"]},
                            help="A value that is exactly one {{reference}} keeps its original type."),
                ConfigField(key="auth.type", label="Authentication", widget="select",
                            options=["none", "bearer", "basic", "header"]),
                ConfigField(key="auth.credential_id", label="Credential", widget="credential",
                            show_if={"auth.type": ["bearer", "basic", "header"]}),
                ConfigField(key="timeout_seconds", label="Timeout (seconds)", widget="number"),
                ConfigField(key="response_format", label="Response format", widget="select",
                            options=["auto", "json", "text"]),
                ConfigField(key="ignore_http_errors", label="Treat non-2xx as success", widget="boolean"),
                ConfigField(key="follow_redirects", label="Follow redirects", widget="boolean"),
            ],
            output_schema={
                "type": "object",
                "properties": {"status_code": {"type": "integer"}, "headers": {"type": "object"}, "body": {},
                               "url": {"type": "string"}, "elapsed_ms": {"type": "number"}},
            },
        ),
    ]
