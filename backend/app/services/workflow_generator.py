"""Orchestrates workflow generation, Pydantic validation, graph validation, retries, and optional review."""

import json
import logging
from typing import List, Optional

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.workflow import WorkflowSchema
from app.services.llm_service import LLMService
from app.services.workflow_reviewer import WorkflowReviewer
from app.validators.graph_validator import GraphValidator

logger = logging.getLogger(__name__)


class WorkflowGenerationError(RuntimeError):
    """Raised when a valid workflow cannot be produced after all retries."""

    def __init__(self, message: str, errors: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class WorkflowGenerator:
    """Coordinates LLM generation, schema/graph validation, retry loop, and optional review."""

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._llm_service = llm_service or LLMService(settings=self._settings)
        self._reviewer = WorkflowReviewer(llm_service=self._llm_service)

    def generate(self, prompt: str, enable_review: Optional[bool] = None) -> WorkflowSchema:
        """Generate and validate a workflow from a natural-language prompt.

        Retries up to `settings.MAX_GENERATION_RETRIES` (default 2) times if JSON
        parsing, Pydantic validation, or graph validation fails.
        """
        max_retries = max(0, self._settings.MAX_GENERATION_RETRIES)
        should_review = (
            enable_review if enable_review is not None else self._settings.ENABLE_WORKFLOW_REVIEW
        )

        if not self._settings.has_gemini_api_key:
            if self._settings.MOCK_DEV_MODE:
                logger.warning(
                    "GEMINI_API_KEY is not configured. Running in MOCK DEV MODE with domain-aware fallback."
                )
                from app.services.mock_workflow_generator import generate_mock_workflow

                mock_wf = generate_mock_workflow(prompt)
                graph_result = GraphValidator.validate(mock_wf)
                if not graph_result.is_valid:
                    raise WorkflowGenerationError(
                        "Mock workflow failed graph validation.", errors=graph_result.errors
                    )
                return mock_wf

        last_raw_output = ""
        last_errors: List[str] = []
        workflow: Optional[WorkflowSchema] = None

        for attempt in range(max_retries + 1):
            if attempt == 0:
                last_raw_output = self._llm_service.generate_workflow_json(prompt)
            else:
                logger.info(
                    "Retrying workflow generation (attempt %d/%d) due to validation errors: %s",
                    attempt,
                    max_retries,
                    last_errors,
                )
                last_raw_output = self._llm_service.fix_workflow_json(
                    original_prompt=prompt,
                    previous_output=last_raw_output,
                    validation_errors=last_errors,
                )

            workflow, last_errors = self._parse_and_validate(last_raw_output)
            if workflow is not None:
                break

        if workflow is None:
            raise WorkflowGenerationError(
                f"Failed to generate a valid workflow after {max_retries + 1} attempts.",
                errors=last_errors,
            )

        if should_review:
            review_result = self._reviewer.review(original_prompt=prompt, workflow=workflow)
            if not review_result.passed and review_result.missing_requirements:
                logger.info(
                    "Workflow self-review flagged missing requirements: %s",
                    review_result.missing_requirements,
                )
                repaired_raw = self._llm_service.fix_workflow_json(
                    original_prompt=prompt,
                    previous_output=workflow.model_dump_json(indent=2),
                    validation_errors=[
                        f"Missing requirement from review: {req}"
                        for req in review_result.missing_requirements
                    ],
                )
                repaired_workflow, repair_errors = self._parse_and_validate(repaired_raw)
                if repaired_workflow is not None:
                    workflow = repaired_workflow
                else:
                    logger.warning(
                        "Review-driven repair failed validation (%s); returning previously validated workflow.",
                        repair_errors,
                    )

        return workflow

    @staticmethod
    def _parse_and_validate(raw_json: str) -> tuple[Optional[WorkflowSchema], List[str]]:
        """Parse JSON, validate Pydantic schema, and run GraphValidator."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            return None, [f"Invalid JSON output from LLM: {exc}"]

        try:
            workflow = WorkflowSchema.model_validate(data)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(part) for part in err['loc']) or 'root'}: {err['msg']}"
                for err in exc.errors()
            ]
            return None, errors

        graph_result = GraphValidator.validate(workflow)
        if not graph_result.is_valid:
            return None, graph_result.errors

        return workflow, []
