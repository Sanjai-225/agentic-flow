"""Orchestrates workflow generation, validation, semantic review, correction, and re-review."""

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.review import ReviewStatus, WorkflowReview
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
    """Coordinates LLM generation, schema/graph validation, retry loop, semantic review, and correction."""

    def __init__(
        self,
        llm_service: Optional[LLMService] = None,
        settings: Optional[Settings] = None,
        registry: Optional[NodeRegistry] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._registry = registry or get_default_registry()
        self._llm_service = llm_service or LLMService(settings=self._settings, registry=self._registry)
        self._reviewer = WorkflowReviewer(llm_service=self._llm_service, registry=self._registry)

    def generate(self, prompt: str, enable_review: Optional[bool] = None) -> Dict[str, Any]:
        """Generate, validate, review, and optionally correct a workflow.

        Returns a dict containing the workflow fields plus review metadata.
        """
        max_retries = max(0, self._settings.MAX_GENERATION_RETRIES)
        should_review = (
            enable_review if enable_review is not None else self._settings.ENABLE_WORKFLOW_REVIEW
        )

        # --- Mock dev mode ---
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
                return self._build_response(mock_wf)

        # --- LLM generation with retry loop ---
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

        # --- Build base response ---
        result = self._build_response(workflow)

        # --- Semantic review ---
        if should_review:
            result = self._run_review_and_correction(prompt, workflow, result)

        return result

    def _run_review_and_correction(
        self,
        prompt: str,
        workflow: WorkflowSchema,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run semantic review, and if it fails, attempt correction and re-review."""
        max_corrections = self._settings.MAX_REVIEW_CORRECTION_ATTEMPTS
        correction_attempts = 0

        review = self._reviewer.review(original_prompt=prompt, workflow=workflow)
        result = self._attach_review(result, review, correction_attempts)

        while review.status == ReviewStatus.FAILED and correction_attempts < max_corrections:
            correction_attempts += 1
            logger.info(
                "Workflow review failed. Correction attempt %d/%d.",
                correction_attempts,
                max_corrections,
            )

            # Build correction prompt from reviewer issues
            issues_for_correction = [
                f"Reviewer issue [{issue.severity}]: {issue.description}"
                + (f" (Suggested: {issue.suggested_correction})" if issue.suggested_correction else "")
                for issue in review.issues
            ]
            if not issues_for_correction:
                issues_for_correction = [f"Review failed: {review.summary}"]

            try:
                corrected_raw = self._llm_service.fix_workflow_json(
                    original_prompt=prompt,
                    previous_output=workflow.model_dump_json(indent=2),
                    validation_errors=issues_for_correction,
                )
            except Exception as exc:
                logger.warning("Correction LLM call failed: %s", exc)
                break

            corrected_wf, errors = self._parse_and_validate(corrected_raw)
            if corrected_wf is None:
                logger.warning("Corrected workflow failed validation: %s", errors)
                break

            workflow = corrected_wf
            review = self._reviewer.review(original_prompt=prompt, workflow=workflow)
            result = self._build_response(workflow)
            result = self._attach_review(result, review, correction_attempts)

        return result

    @staticmethod
    def _build_response(workflow: WorkflowSchema) -> Dict[str, Any]:
        """Build the base response dict from a WorkflowSchema."""
        data = workflow.model_dump()
        data["review_status"] = None
        data["review_summary"] = None
        data["review_issues"] = None
        data["requirement_coverage"] = None
        data["correction_attempts"] = 0
        data["clarification_required"] = False
        return data

    @staticmethod
    def _attach_review(
        result: Dict[str, Any],
        review: WorkflowReview,
        correction_attempts: int,
    ) -> Dict[str, Any]:
        """Attach review metadata to the response dict."""
        result["review_status"] = review.status.value
        result["review_summary"] = review.summary
        result["review_issues"] = [issue.model_dump() for issue in review.issues]
        result["requirement_coverage"] = [cov.model_dump() for cov in review.requirement_coverage]
        result["correction_attempts"] = correction_attempts
        result["clarification_required"] = review.clarification_required
        return result

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
