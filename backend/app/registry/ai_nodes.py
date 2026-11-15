"""AI node definitions (Milestone 2): real inference through the OpenAI / Anthropic / Gemini provider layer."""

from typing import List

from app.registry.configs import AgentConfig, AIGenerateConfig
from app.registry.output_hooks import infer_ai
from app.schemas.registry import (
    ConfigField,
    NodeCategory,
    NodeDefinition,
    PortDataType,
    PortDefinition,
    PortType,
)
from app.schemas.workflow import RetryPolicy

_MODEL_HELP = ("Provider and verified model. The API key comes from the selected credential, or from the platform "
               "key when none is selected (if the server allows platform keys).")


def _in(id_: str, name: str) -> PortDefinition:
    return PortDefinition(id=id_, name=name, port_type=PortType.INPUT, data_type=PortDataType.ANY)


def _out(id_: str, name: str) -> PortDefinition:
    return PortDefinition(id=id_, name=name, port_type=PortType.OUTPUT, data_type=PortDataType.ANY)


def ai_definitions() -> List[NodeDefinition]:
    return [
        NodeDefinition(
            operation_id="ai.generate",
            node_type="ai_generate",
            label="AI Generate",
            category=NodeCategory.AI_AGENT,
            description="One bounded model call: summarise, rewrite, classify, extract or generate text, or "
                        "return JSON validated against an output schema. No tools, no autonomous loop.",
            inputs=[_in("in_data", "Input")],
            outputs=[_out("out_result", "Result")],
            default_config={"model": {"provider": "gemini", "model": "gemini-3.5-flash", "max_output_tokens": 1024,
                                      "timeout_seconds": 60},
                            "system_prompt": "", "prompt": "", "inputs": {}, "output_format": "text"},
            icon="sparkles",
            tags=["ai", "llm", "generate", "summarize", "classify", "extract", "openai", "anthropic", "gemini"],
            executable=True,
            status="ready",
            config_model=AIGenerateConfig,
            id_prefix="ai_generate",
            infer_output=infer_ai,
            side_effects=False,
            idempotent=True,
            default_retry=RetryPolicy(max_attempts=1),
            default_timeout_seconds=300,
            ai_guidance="Use for a single model step. `prompt` may contain {{...}} references; put structured "
                        "upstream data in `inputs`. For JSON set output_format 'json' and an object "
                        "`output_schema`; downstream nodes read {{nodes.<id>.output.result.<field>}}.",
            ui_fields=[
                ConfigField(key="model", label="Model", widget="model_select", required=True, help=_MODEL_HELP),
                ConfigField(key="system_prompt", label="System instructions", widget="textarea",
                            supports_expressions=True),
                ConfigField(key="prompt", label="Prompt", widget="textarea", required=True, supports_expressions=True,
                            placeholder="Summarise this message: {{trigger.message}}"),
                ConfigField(key="inputs", label="Mapped inputs", widget="keyvalue_json", supports_expressions=True,
                            help="Sent to the model as JSON after the prompt."),
                ConfigField(key="output_format", label="Output", widget="select", options=["text", "json"]),
                ConfigField(key="output_schema", label="Output schema (JSON Schema)", widget="json_schema",
                            show_if={"output_format": ["json"]}),
                ConfigField(key="max_repair_attempts", label="Repair attempts for invalid JSON", widget="number",
                            show_if={"output_format": ["json"]}),
                ConfigField(key="max_retries", label="Retries on provider errors", widget="number"),
            ],
            output_schema={"type": "object", "properties": {
                "result": {"description": "Text, or the schema-validated JSON object"}, "provider": {"type": "string"},
                "model": {"type": "string"}, "usage": {"type": "object"}, "finish_reason": {}}},
        ),
        NodeDefinition(
            operation_id="ai.agent",
            node_type="ai_agent",
            label="AI Agent",
            category=NodeCategory.AI_AGENT,
            description="Configurable agent (LangGraph) that reasons over mapped inputs and may call explicitly "
                        "allowed tools in a bounded loop, then returns text or schema-validated JSON. One node type "
                        "for many tasks: the instructions, tools and output schema define the task.",
            inputs=[_in("in_data", "Input")],
            outputs=[_out("out_result", "Result")],
            default_config={"model": {"provider": "gemini", "model": "gemini-3.5-flash", "max_output_tokens": 2048,
                                      "timeout_seconds": 60},
                            "instructions": "", "task": "", "inputs": {}, "tools": [],
                            "limits": {"max_iterations": 6, "max_tool_calls": 10, "timeout_seconds": 120}},
            icon="bot",
            tags=["ai", "agent", "llm", "tools", "langgraph", "reasoning", "openai", "anthropic", "gemini"],
            executable=True,
            status="ready",
            config_model=AgentConfig,
            id_prefix="agent",
            infer_output=infer_ai,
            side_effects=False,  # refined per selected tools by the executor
            idempotent=True,
            default_retry=RetryPolicy(max_attempts=1),
            default_timeout_seconds=600,
            ai_guidance="Use when the task needs multi-step reasoning or tools. Put the role and rules in "
                        "`instructions`, the request in `task`, upstream data in `inputs`, and list ONLY the "
                        "needed tool ids in `tools` (calculator, datetime, json_tools, text_tools, data_aggregate, "
                        "http_get). Add an object `output_schema` for structured results; read them downstream "
                        "with {{nodes.<id>.output.result.<field>}}.",
            ui_fields=[
                ConfigField(key="model", label="Primary model", widget="model_select", required=True, help=_MODEL_HELP),
                ConfigField(key="fallback_model", label="Fallback model (optional)", widget="model_select",
                            help="Used only when the primary provider is unavailable (rate limit, outage, timeout); "
                                 "never for auth, permission, tool or output errors."),
                ConfigField(key="instructions", label="Agent instructions", widget="textarea", required=True,
                            supports_expressions=True,
                            placeholder="You are a support triage agent. Classify the message and ..."),
                ConfigField(key="task", label="Task", widget="textarea", supports_expressions=True,
                            placeholder="Analyse {{trigger.message}}"),
                ConfigField(key="inputs", label="Mapped inputs", widget="keyvalue_json", supports_expressions=True),
                ConfigField(key="tools", label="Allowed tools", widget="tool_select",
                            help="The agent can only call the tools selected here."),
                ConfigField(key="output_schema", label="Output schema (JSON Schema, optional)", widget="json_schema"),
                ConfigField(key="limits.max_iterations", label="Max iterations", widget="number"),
                ConfigField(key="limits.max_tool_calls", label="Max tool calls", widget="number"),
                ConfigField(key="limits.tool_timeout_seconds", label="Per-tool timeout (s)", widget="number"),
                ConfigField(key="limits.timeout_seconds", label="Overall agent timeout (s)", widget="number"),
                ConfigField(key="limits.max_total_tokens", label="Token budget (optional)", widget="number"),
                ConfigField(key="limits.max_repair_attempts", label="Output repair attempts", widget="number"),
            ],
            output_schema={"type": "object", "properties": {
                "result": {"description": "Final answer: text, or the schema-validated JSON object"},
                "provider": {"type": "string"}, "model": {"type": "string"}, "fallback_used": {"type": "boolean"},
                "fallback_reason": {}, "iterations": {"type": "integer"}, "tool_calls": {"type": "array"},
                "usage": {"type": "object"}}},
        ),
    ]
