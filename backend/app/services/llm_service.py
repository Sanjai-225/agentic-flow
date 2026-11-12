"""Gemini API integration using the official google-genai SDK."""

import re
from typing import Optional

from google import genai
from google.genai import types

from app.core.config import Settings, get_settings


class LLMConfigurationError(RuntimeError):
    """Raised when the Gemini API key or client configuration is missing/invalid."""


class LLMGenerationError(RuntimeError):
    """Raised when the Gemini API call fails."""


WORKFLOW_ARCHITECT_SYSTEM_PROMPT = """You are an expert AI Workflow Architect.
Your job is to transform a user's natural-language requirement into a complete, well-structured, executable workflow graph in JSON.

Follow these 6 architectural stages internally before producing your final JSON:
1. Understand the user requirement: Identify objectives, triggers, inputs, operations, dependencies, integrations, error-handling needs, and constraints.
2. Decompose into meaningful operations: Break the requirement into clear, atomic, cohesive workflow steps.
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
    """Wrapper around google-genai for structured workflow JSON generation."""

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

    def generate_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """Call Gemini and return raw JSON text (with any markdown fences stripped)."""
        client = self._get_client()
        try:
            response = client.models.generate_content(
                model=self._settings.GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
        except LLMConfigurationError:
            raise
        except Exception as exc:
            raise LLMGenerationError(f"Gemini API request failed: {exc}") from exc

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise LLMGenerationError("Gemini API returned an empty response.")

        return _strip_markdown_fences(text)

    def generate_workflow_json(self, prompt: str) -> str:
        """Generate a workflow JSON string from a natural-language requirement."""
        user_prompt = (
            "Design a complete workflow for the following requirement.\n\n"
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
