"""Gemini API integration using REST and official google-genai SDK."""

import json
import logging
import re
from typing import List, Optional
import urllib.error
import urllib.request

from google import genai
from google.genai import types

from app.core.config import Settings, get_settings
from app.registry.node_registry import NodeRegistry, get_default_registry

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the Gemini API key or client configuration is missing/invalid."""


class LLMGenerationError(RuntimeError):
    """Raised when the Gemini API call fails."""


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
3. Identify appropriate nodes from registry:
   - Select matching node types from the standard Node Registry above whenever applicable (e.g. `webhook_trigger`, `schedule_trigger`, `email_trigger`, `manual_trigger`, `email_output`, `notification_output`, `webhook_output`, `llm_agent`, `text_classifier`, `entity_extractor`, `summarizer`, `api_call`, `database_query`, `database_update`, `file_operation`, `tool_integration`, `condition`, `switch`, `loop`, `error_handler`, `data_transform`, `filter`, `code_execution`, `vector_search`, `knowledge_retrieval`, `human_approval`, etc.).
   - If an operation requires a novel or domain-specific capability not in the registry (e.g. `document_ocr`, `audio_transcription`), invent a descriptive snake_case type following the same semantic patterns.
4. Identify tools/integrations: Whenever a node interacts with an external service or tool (e.g., Gmail, Slack, GitHub, PostgreSQL, Stripe, OpenAI, Jira, Notion, etc.), populate its `tool` object with `name`, `operation`, and `"status": "not_connected"` (because this is design-only).
5. Design the workflow graph: Connect nodes with directed edges supporting sequential flows, parallel branches, and conditional paths (using `label` and `condition` on edges). Ensure every node is reachable from `start_nodes` and can reach at least one node in `end_nodes`.
6. Self-review against original requirements: Verify that every requirement, edge case, and integration from the prompt is covered and that there are no orphan nodes, broken edge references, or missing terminal paths.

STRICT OUTPUT RULES:
- Return ONLY valid JSON. Do NOT include markdown fences (no ```json or ```), commentary, or extra text.
- Do NOT include `x` or `y` position fields anywhere; layout is handled by the frontend.
- Every node ID and edge ID must be unique.
- Every edge `source` and `target` must reference an existing node ID.
- `start_nodes` and `end_nodes` must be non-empty arrays of valid node IDs.
- Use this exact top-level JSON structure:
{{
  "workflow_id": "unique-kebab-case-id",
  "workflow_name": "Descriptive Workflow Name",
  "description": "Clear summary of what this workflow accomplishes.",
  "nodes": [
    {{
      "id": "node_1",
      "type": "webhook_trigger",
      "label": "Human Readable Label",
      "description": "What this step does.",
      "config": {{}},
      "tool": {{
        "name": "ServiceName",
        "operation": "operation_name",
        "status": "not_connected"
      }}
    }}
  ],
  "edges": [
    {{
      "id": "edge_1",
      "source": "node_1",
      "target": "node_2",
      "label": "Optional label",
      "condition": "Optional condition expression"
    }}
  ],
  "start_nodes": ["node_1"],
  "end_nodes": ["node_N"]
}}
Note: `tool` on a node is optional (omit or set to null if no external tool is used). `label` and `condition` on an edge are optional.
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
            self._client = genai.Client(api_key=self._settings.GEMINI_API_KEY)
        return self._client

    def _call_rest(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        timeout: int = 12,
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        timeout: int = 12,
    ) -> str:
        """Try REST first, then SDK for a single model. Returns raw JSON text."""
        # 1. Try robust REST HTTP call first
        try:
            logger.info(f"Calling model: {model_name} (REST, timeout={timeout}s)")
            return self._call_rest(model_name, system_prompt, user_prompt, temperature, timeout)
        except Exception as exc:
            logger.warning(f"REST attempt failed for {model_name}: {exc}")

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
        except LLMGenerationError:
            raise
        except Exception as exc:
            raise LLMGenerationError(f"Both REST and SDK failed for {model_name}: {exc}") from exc

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Call Gemini across generator candidate models and return raw JSON text."""
        if not self._settings.has_gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured.")

        candidate_models = [self._settings.GEMINI_MODEL]
        fallback = self._settings.GEMINI_FALLBACK_MODEL
        if fallback and fallback not in candidate_models:
            candidate_models.append(fallback)

        last_exc: Optional[Exception] = None
        for model_name in candidate_models:
            try:
                return self._call_model(model_name, system_prompt, user_prompt, temperature, timeout=12)
            except Exception as exc:
                logger.warning(f"Model {model_name} failed: {exc}")
                last_exc = exc
                continue

        raise LLMGenerationError(
            f"Gemini API request failed across generator models {candidate_models}: {last_exc}"
        ) from last_exc

    def generate_review_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> str:
        """Call the reviewer model (gemma-4-31b-it) with a longer timeout. No fallback to generator models."""
        if not self._settings.has_gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured.")

        reviewer_model = self._settings.GEMINI_REVIEWER_MODEL
        logger.info(f"Calling reviewer model: {reviewer_model} (timeout=60s)")
        return self._call_model(reviewer_model, system_prompt, user_prompt, temperature, timeout=60)

    def generate_workflow_json(self, prompt: str) -> str:
        """Generate a workflow JSON string from a natural-language requirement using Node Registry knowledge."""
        user_prompt = (
            "Design a complete, highly tailored workflow for the following requirement.\n"
            "Select appropriate standard node types and tool configurations from the Node Registry.\n\n"
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
