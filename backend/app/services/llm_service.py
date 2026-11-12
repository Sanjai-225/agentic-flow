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

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the Gemini API key or client configuration is missing/invalid."""


class LLMGenerationError(RuntimeError):
    """Raised when the Gemini API call fails."""


WORKFLOW_ARCHITECT_SYSTEM_PROMPT = """You are an expert AI Workflow Architect.
Your job is to transform a user's natural-language requirement into a complete, well-structured, executable workflow graph in JSON.

Follow these 6 architectural stages internally before producing your final JSON:
1. Understand the user requirement: Identify objectives, triggers, inputs, operations, dependencies, integrations, error-handling needs, and constraints.
2. Decompose into meaningful operations: Break the requirement into clear, atomic, cohesive workflow steps tailored uniquely to what the user asked.
3. Identify appropriate nodes: Dynamically choose the most fitting node `type` for each step (e.g., trigger, webhook, schedule, condition, branch, transform, filter, llm_agent, api_call, database_query, notification, approval, loop, end, etc.). Do NOT limit yourself to a fixed registry; invent descriptive snake_case types when appropriate.
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
{
  "workflow_id": "unique-kebab-case-id",
  "workflow_name": "Descriptive Workflow Name",
  "description": "Clear summary of what this workflow accomplishes.",
  "nodes": [
    {
      "id": "node_1",
      "type": "trigger",
      "label": "Human Readable Label",
      "description": "What this step does.",
      "config": {},
      "tool": {
        "name": "ServiceName",
        "operation": "operation_name",
        "status": "not_connected"
      }
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "source": "node_1",
      "target": "node_2",
      "label": "Optional label",
      "condition": "Optional condition expression"
    }
  ],
  "start_nodes": ["node_1"],
  "end_nodes": ["node_N"]
}
Note: `tool` on a node is optional (omit or set to null if no external tool is used). `label` and `condition` on an edge are optional.
"""


def _strip_markdown_fences(text: str) -> str:
    """Remove accidental markdown code fences around JSON responses."""
    cleaned = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()
    return cleaned


class LLMService:
    """Wrapper for structured workflow JSON generation with dual REST and SDK execution."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._client: Optional[genai.Client] = None

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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMGenerationError(f"No candidates returned by Gemini ({clean_model}).")
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text or not text.strip():
                raise LLMGenerationError(f"Empty text in Gemini response ({clean_model}).")
            return _strip_markdown_fences(text)

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Call Gemini across candidate models and return raw JSON text."""
        if not self._settings.has_gemini_api_key:
            raise LLMConfigurationError("GEMINI_API_KEY is not configured.")

        candidate_models = [self._settings.GEMINI_MODEL]
        for fallback in ["gemini-3-flash-preview", "gemini-3.1-flash-lite-preview", "gemini-3.8-flash"]:
            if fallback not in candidate_models:
                candidate_models.append(fallback)

        last_exc: Optional[Exception] = None
        for model_name in candidate_models:
            # 1. Try robust REST HTTP call first
            try:
                logger.info(f"Generating workflow with model: {model_name} (REST)")
                return self._call_rest(model_name, system_prompt, user_prompt, temperature)
            except Exception as exc:
                logger.warning(f"REST attempt failed for {model_name}: {exc}")
                last_exc = exc

            # 2. Try SDK as secondary fallback
            try:
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
            except Exception as exc:
                logger.warning(f"SDK attempt failed for {model_name}: {exc}")
                last_exc = exc
                continue

        raise LLMGenerationError(
            f"Gemini API request failed across candidate models: {last_exc}"
        ) from last_exc

    def generate_workflow_json(self, prompt: str) -> str:
        """Generate a workflow JSON string from a natural-language requirement."""
        user_prompt = (
            "Design a complete, highly tailored workflow for the following requirement.\n\n"
            f"Requirement:\n{prompt}"
        )
        return self.generate_json(
            system_prompt=WORKFLOW_ARCHITECT_SYSTEM_PROMPT,
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
            "Fix ALL validation errors while preserving requirement coverage. "
            "Return ONLY valid JSON with no markdown fences and no x/y positions."
        )
        return self.generate_json(
            system_prompt=WORKFLOW_ARCHITECT_SYSTEM_PROMPT,
            user_prompt=repair_prompt,
            temperature=0.1,
        )
