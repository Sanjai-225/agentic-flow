"""Gemini API integration using REST and official google-genai SDK."""

import json
import logging
import re
from typing import Optional
import urllib.error
import urllib.request

from google import genai
from google.genai import types

from app.core.config import Settings, get_settings
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.services.llm_errors import (
    GeminiHTTPError,
    LLMErrorInfo,
    classify_llm_error,
    most_relevant,
    scrub_secrets,
)

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the Gemini API key or client configuration is missing/invalid."""


class LLMGenerationError(RuntimeError):
    """Raised when the Gemini API call fails.

    ``info`` (an ``LLMErrorInfo``) carries the user-facing category, message and
    suggestion; ``str(exc)`` is always the scrubbed user-facing message.
    """

    def __init__(self, message: str, info: Optional["LLMErrorInfo"] = None) -> None:
        super().__init__(scrub_secrets(message))
        self.info = info


def build_architect_system_prompt(registry: Optional[NodeRegistry] = None) -> str:
    """Build the Workflow Architect system prompt infused with live Node Registry knowledge."""
    reg = registry or get_default_registry()
    catalog_text = reg.get_catalog_for_prompt()

    return f"""You are an expert AI Workflow Architect.
Your job is to transform a user's natural-language requirement into a complete, well-structured, executable workflow graph in JSON.

{catalog_text}

Follow these 6 architectural stages internally before producing your final JSON:
1. Understand the user requirement: Identify objectives, triggers, inputs, operations, dependencies, integrations, error-handling needs, and constraints.
2. Decompose into meaningful operations: Break the requirement into clear, atomic, cohesive workflow steps tailored uniquely to what the user asked.
3. Select operations ONLY from the Node Registry above. Every listed operation executes; nothing else exists.
   Never invent node types or operations. Never add design-only, placeholder or "not connected" nodes.
4. External services: there are no built-in application integrations yet (no Gmail, Slack, databases, file
   storage, etc.). When the requirement needs an external system, call its HTTP API with `http.request`
   (credentials are referenced by id and configured by the user later), or explain the limitation in the
   workflow `description`. Do not set a `tool` object.
5. Design the workflow graph: exactly one trigger node; connect nodes with directed edges using the exact
   output port names listed for each operation (conditional paths use `core.if` true/false ports or
   `core.switch` case ports). Ensure every node is reachable from the trigger.
6. Self-review against original requirements: Verify that every requirement is covered with registered
   operations, every config matches its operation's config example shape, every {{{{nodes.<id>.output...}}}}
   reference points to an upstream node, and there are no orphan nodes or broken edge references.

STRICT OUTPUT RULES:
- Return ONLY valid JSON. Do NOT include markdown fences (no ```json or ```), commentary, or extra text.
- Do NOT include `x` or `y` position fields anywhere; layout is handled by the frontend.
- Every node ID and edge ID must be unique.
- Node IDs follow the predictable pattern `<id prefix>_<n>` listed for each operation (e.g. `manual_trigger_1`,
  `set_1`, `set_2`, `if_1`, `http_1`, `end_1`); `{{{{nodes.<id>.output...}}}}` references must use these exact IDs.
- Every edge `source` and `target` must reference an existing node ID.
- `start_nodes` and `end_nodes` must be non-empty arrays of valid node IDs.
- Use this exact top-level JSON structure:
{{
  "workflow_id": "unique-kebab-case-id",
  "workflow_name": "Descriptive Workflow Name",
  "description": "Clear summary of what this workflow accomplishes.",
  "nodes": [
    {{
      "id": "webhook_trigger_1",
      "type": "webhook_trigger",
      "operation": "core.webhook_trigger",
      "label": "Human Readable Label",
      "description": "What this step does.",
      "config": {{"method": "POST"}}
    }}
  ],
  "edges": [
    {{
      "id": "edge_1",
      "source": "webhook_trigger_1",
      "target": "set_1",
      "source_port": "main",
      "target_port": "main"
    }}
  ],
  "start_nodes": ["webhook_trigger_1"],
  "end_nodes": ["end_1"]
}}
Every node MUST set `operation` to one of the registry operation ids above, and `config` must use only that
operation's config keys. An edge's `source_port` must be one of the source operation's output ports (e.g. "true"
or "false" for `core.if`, a case key or "default" for `core.switch`); `target_port` is "main" unless the target
lists other input ports (e.g. "input_1"/"input_2" for `core.merge`).
"""


WORKFLOW_ARCHITECT_SYSTEM_PROMPT = build_architect_system_prompt()


def _strip_markdown_fences(text: str) -> str:
    """Remove accidental markdown code fences around JSON responses."""
    cleaned = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return cleaned


class LLMService:
    """Wrapper for structured workflow JSON generation with dual REST and SDK execution."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        registry: Optional[NodeRegistry] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client: Optional[genai.Client] = None
        self._registry = registry or get_default_registry()
        self._architect_system_prompt = build_architect_system_prompt(self._registry)

    def _get_client(self) -> genai.Client:
        if not self._settings.has_gemini_api_key:
            raise LLMConfigurationError(
                "GEMINI_API_KEY is not configured. Set GEMINI_API_KEY in backend/.env."
            )
        if self._client is None:
            self._client = genai.Client(
                api_key=self._settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(api_version="v1beta"),
            )
        return self._client

    def _call_rest(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        timeout: int = 30,
    ) -> str:
        """Execute request via REST HTTP/1.1 endpoint (avoids Windows SSL/HTTP2 negotiation bugs)."""
        key = self._settings.GEMINI_API_KEY
        clean_model = model_name.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={key}"
        payload = json.dumps({
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": temperature,
            },
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            resp_cm = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # Keep Google's structured error (status/message) for classification; the URL (with key) is dropped.
            raise GeminiHTTPError.from_http_error(exc) from None
        with resp_cm as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMGenerationError(f"No candidates returned by Gemini ({clean_model}).")
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text or not text.strip():
                raise LLMGenerationError(f"Empty text in Gemini response ({clean_model}).")
            return _strip_markdown_fences(text)

    def _call_model(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        timeout: int = 30,
    ) -> str:
        """Try REST first, then SDK for a single model. Returns raw JSON text.

        Raises ``LLMGenerationError`` whose ``info`` classifies the failure.
        """
        # 1. Try robust REST HTTP call first
        try:
            logger.info(f"Calling model: {model_name} (REST, timeout={timeout}s)")
            return self._call_rest(model_name, system_prompt, user_prompt, temperature, timeout)
        except Exception as exc:
            rest_info = classify_llm_error(exc, model_name)
            logger.warning("REST attempt failed for %s: [%s] %s", model_name, rest_info.category,
                           scrub_secrets(str(exc), [self._settings.GEMINI_API_KEY]))
        # The SDK cannot fix a rejected key, a missing model or an exhausted quota; it only helps with
        # transport problems (e.g. Windows TLS/HTTP2 quirks).
        if rest_info.category in {"invalid_api_key", "permission_denied", "quota_exceeded", "model_not_found"}:
            raise LLMGenerationError(rest_info.message, rest_info)

        # 2. Try SDK as secondary fallback
        try:
            logger.info(f"Calling model: {model_name} (SDK)")
            client = self._get_client()
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
            text = getattr(response, "text", None)
            if text and text.strip():
                return _strip_markdown_fences(text)
            raise LLMGenerationError(f"Empty text in SDK response ({model_name}).")
        except Exception as exc:
            sdk_info = classify_llm_error(exc, model_name)
            logger.warning("SDK attempt failed for %s: [%s] %s", model_name, sdk_info.category,
                           scrub_secrets(str(exc), [self._settings.GEMINI_API_KEY]))
            info = most_relevant([rest_info, sdk_info]) or sdk_info
            raise LLMGenerationError(info.message, info) from None

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Call Gemini across generator candidate models and return raw JSON text."""
        if not self._settings.has_gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured.")

        candidate_models = [self._settings.GEMINI_MODEL]
        for fb in [self._settings.GEMINI_FALLBACK_MODEL, "gemini-3-flash-preview"]:
            if fb and fb not in candidate_models:
                candidate_models.append(fb)

        return self._call_candidates(candidate_models, system_prompt, user_prompt, temperature, "generator")

    def _call_candidates(self, models: list[str], system_prompt: str, user_prompt: str, temperature: float,
                         role: str) -> str:
        """Try each model in order; stop early when another model cannot help (bad key, network down)."""
        infos: list[LLMErrorInfo] = []
        for model_name in models:
            try:
                return self._call_model(model_name, system_prompt, user_prompt, temperature, timeout=30)
            except Exception as exc:
                info = classify_llm_error(exc, model_name)
                infos.append(info)
                logger.warning("%s model %s failed: [%s] %s", role, model_name, info.category, info.message)
                if not info.retry_other_models:
                    break
        info = most_relevant(infos) or classify_llm_error(RuntimeError("no models configured"))
        tried = ", ".join(models[: len(infos)])
        raise LLMGenerationError(f"{info.message} (tried {role} model(s): {tried})", info)

    def generate_review_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """Call the reviewer model with resilient fallback."""
        if not self._settings.has_gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured.")

        reviewer_candidates = [self._settings.GEMINI_REVIEWER_MODEL]
        if "gemini-3-flash-preview" not in reviewer_candidates:
            reviewer_candidates.append("gemini-3-flash-preview")

        return self._call_candidates(reviewer_candidates, system_prompt, user_prompt, temperature, "reviewer")

    def generate_workflow_json(self, prompt: str) -> str:
        """Generate a workflow JSON string from a natural-language requirement using Node Registry knowledge."""
        user_prompt = (
            "Design a complete, highly tailored workflow for the following requirement.\n"
            "Use only operations from the Node Registry.\n\n"
            f"Requirement:\n{prompt}"
        )
        return self.generate_json(
            system_prompt=self._architect_system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
        )

    def fix_workflow_json(
        self,
        original_prompt: str,
        previous_output: str,
        validation_errors: list[str],
    ) -> str:
        """Ask Gemini to repair an invalid workflow JSON using specific validation errors."""
        error_list = "\n".join(f"- {err}" for err in validation_errors)
        repair_prompt = (
            "The previously generated workflow JSON failed validation.\n\n"
            f"Original Requirement:\n{original_prompt}\n\n"
            f"Validation Errors:\n{error_list}\n\n"
            f"Previous Output:\n{previous_output}\n\n"
            "Fix ALL validation errors while preserving requirement coverage and adhering to Node Registry conventions. "
            "Return ONLY valid JSON with no markdown fences and no x/y positions."
        )
        return self.generate_json(
            system_prompt=self._architect_system_prompt,
            user_prompt=repair_prompt,
            temperature=0.1,
        )
