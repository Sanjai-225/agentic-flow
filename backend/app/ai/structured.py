"""Text and structured (JSON Schema) generation shared by AI Generate and the AI Agent.

Structured output uses each provider's native JSON-schema mode through LangChain, then validates the
result against the *user's* schema with ``jsonschema``. Invalid output triggers a bounded repair loop
(the validation errors are sent back to the same model); if it still fails the node fails with
STRUCTURED_OUTPUT_INVALID. Malformed output is never accepted silently, and output-validation failures
never trigger a provider fallback.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel

from app.ai.providers import structured_runnable
from app.ai.router import ModelRouter
from app.core.errors import ErrorCategory, NodeExecutionError

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
MAX_SCHEMA_BYTES = 32_000


def schema_problems(schema: Any) -> List[str]:
    """Validation of a user-supplied output schema (empty list = usable)."""
    if not isinstance(schema, dict):
        return ["The output schema must be a JSON object (a JSON Schema)."]
    if len(json.dumps(schema)) > MAX_SCHEMA_BYTES:
        return [f"The output schema is larger than {MAX_SCHEMA_BYTES} bytes."]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return [f"The output schema is not a valid JSON Schema: {exc.message}"]
    if schema.get("type") != "object":
        return ['The output schema must describe an object (set "type": "object" with "properties").']
    if not isinstance(schema.get("properties"), dict) or not schema["properties"]:
        return ['The output schema must define at least one property under "properties".']
    return []


def message_text(message: Optional[BaseMessage]) -> str:
    """Plain text of a LangChain message (string content or list of content blocks)."""
    if message is None:
        return ""
    content = message.content
    if isinstance(content, str):
        return content
    parts: List[str] = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in ("text", "output_text") and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts)


def _loads_json(text: str) -> Optional[Any]:
    cleaned = text.strip()
    fence = _FENCE.match(cleaned)
    if fence:
        cleaned = fence.group(1)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def validation_errors(schema: Dict[str, Any], data: Any, limit: int = 6) -> List[str]:
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.absolute_path))
    out = []
    for err in errors[:limit]:
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{where}: {err.message}")
    return out


async def generate_text(router: ModelRouter, messages: List[BaseMessage]) -> Tuple[str, AIMessage]:
    async def call(model, info):
        result = await model.ainvoke(messages)
        return result, result

    result: AIMessage = await router.invoke(call)
    text = message_text(result).strip()
    if not text:
        raise NodeExecutionError(ErrorCategory.INVALID_MODEL_OUTPUT, "The model returned an empty response.",
                                 details={"provider": router.active.info.provider,
                                          "model": router.active.info.model})
    return text, result


async def generate_structured(router: ModelRouter, messages: List[BaseMessage], schema: Dict[str, Any],
                              max_repairs: int, trace: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return an object that validates against ``schema`` or raise STRUCTURED_OUTPUT_INVALID."""
    conversation = list(messages)
    last_errors: List[str] = []
    for attempt in range(max_repairs + 1):
        snapshot = list(conversation)

        async def call(model, info, _conv=snapshot):  # noqa: B008 - bound per iteration on purpose
            result = await structured_runnable(model, info.provider, schema).ainvoke(_conv)
            return result, (result.get("raw") if isinstance(result, dict) else None)

        result = await router.invoke(call)
        raw = result.get("raw") if isinstance(result, dict) else None
        parsed = result.get("parsed") if isinstance(result, dict) else None
        raw_text = message_text(raw) if raw is not None else ""
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump()
        if parsed is None and raw_text:
            parsed = _loads_json(raw_text)
        if parsed is None:
            last_errors = ["The response was not valid JSON."]
        else:
            last_errors = validation_errors(schema, parsed)
        if trace is not None:
            trace.append({"type": "structured_output", "attempt": attempt + 1, "valid": not last_errors,
                          "errors": last_errors})
        if not last_errors:
            return parsed
        if attempt < max_repairs:
            conversation = conversation + [
                AIMessage(content=raw_text or (json.dumps(parsed, default=str) if parsed is not None
                                               else "(no output)")),
                HumanMessage(content="Your previous answer did not match the required JSON schema:\n- "
                             + "\n- ".join(last_errors)
                             + "\nReturn only a corrected JSON object that satisfies the schema."),
            ]
    raise NodeExecutionError(
        ErrorCategory.STRUCTURED_OUTPUT_INVALID,
        f"The model output did not match the output schema after {max_repairs + 1} attempt(s): "
        f"{'; '.join(last_errors[:3])}",
        details={"errors": last_errors, "attempts": max_repairs + 1},
    )
