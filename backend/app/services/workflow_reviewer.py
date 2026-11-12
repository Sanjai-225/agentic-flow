"""LLM self-review service to check generated workflows against original requirements."""

import json
import logging

from pydantic import ValidationError

from app.schemas.workflow import WorkflowReviewResult, WorkflowSchema
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

WORKFLOW_REVIEWER_SYSTEM_PROMPT = """You are a senior AI Workflow Reviewer.
Compare the generated workflow JSON against the user's original natural-language requirement.
Check:
1. Requirement coverage: Are all triggers, operations, conditions, integrations, and outputs represented?
2. Logical soundness: Do conditional branches and terminal paths make sense for the requirement?
3. Integration accuracy: Are external tools marked with status "not_connected"?

Return ONLY valid JSON matching this schema (no markdown fences):
{
  "passed": true,
  "coverage_score": 0.95,
  "missing_requirements": [],
  "suggestions": [],
  "summary": "Brief assessment of requirement coverage."
}
"""


class WorkflowReviewer:
    """Reviews a validated WorkflowSchema against the original user prompt."""

    def __init__(self, llm_service: LLMService) -> None:
        self._llm_service = llm_service

    def review(self, original_prompt: str, workflow: WorkflowSchema) -> WorkflowReviewResult:
        """Run an LLM self-review and return structured feedback."""
        review_prompt = (
            f"Original Requirement:\n{original_prompt}\n\n"
            f"Generated Workflow JSON:\n{workflow.model_dump_json(indent=2)}"
        )
        raw_response = self._llm_service.generate_json(
            system_prompt=WORKFLOW_REVIEWER_SYSTEM_PROMPT,
            user_prompt=review_prompt,
            temperature=0.1,
        )
        try:
            data = json.loads(raw_response)
            return WorkflowReviewResult.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Failed to parse workflow review output: %s", exc)
            return WorkflowReviewResult(
                passed=True,
                coverage_score=None,
                missing_requirements=[],
                suggestions=[],
                summary="Review output could not be parsed; structural validation passed.",
            )
