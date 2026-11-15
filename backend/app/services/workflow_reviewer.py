"""LLM-based Workflow Reviewer (Semantic Auditor).

Uses gemma-4-31b-it via a dedicated LLM call to independently verify
the logical correctness and completeness of generated workflows.
"""

import json
import logging

from typing import Optional
from pydantic import ValidationError

from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.review import ReviewStatus, WorkflowReview
from app.schemas.workflow import WorkflowSchema
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)


def build_reviewer_system_prompt(registry: Optional[NodeRegistry] = None) -> str:
    """Build the Reviewer system prompt enriched with Node Registry specifications."""
    reg = registry or get_default_registry()
    catalog_text = reg.get_catalog_for_prompt()

    return f"""You are an independent senior workflow architect and semantic auditor.

{catalog_text}

You receive:
1. The original user prompt describing what the workflow should do.
2. The complete generated workflow JSON with nodes, edges, start_nodes, and end_nodes.

Your job is to independently audit whether the workflow correctly and completely implements the user's requirements, and verify that node types and tools adhere to the standard Node Registry specifications.

## Requirement Understanding
- Examine the original user prompt carefully.
- Identify every explicitly requested operation.
- Identify required inputs and outputs.
- Identify conditions, branches and dependencies.
- Identify constraints and expected outcomes.
- Distinguish mandatory requirements from optional suggestions.
- Do not invent requirements the user never requested.
- Flag ambiguous requirements rather than silently assuming.

## Requirement Coverage
For every identified requirement, determine coverage status:
- "covered": fully implemented with correct node(s) and connection(s)
- "partially_covered": some aspects implemented but incomplete
- "missing": not implemented at all
- "unclear": requirement is ambiguous, cannot determine coverage

Do NOT consider a requirement covered merely because a node has a matching label. Inspect the node's purpose, config, and connections.

## Operation Correctness & Node Registry Alignment
Check:
- Does every node perform an operation relevant to the user's objective?
- Are any requested operations missing?
- Are operations in correct logical order?
- Are node types chosen from the Node Registry where appropriate?
- Are tool selections suitable and compatible with the node operation?
- Are required input/output dependencies represented?

## Conditional Logic
Check:
- Are all requested conditions represented?
- Are success and failure branches correctly created?
- Are branch labels meaningful?
- Does each branch lead to the appropriate operation?
- Are any required branches missing?

## Workflow Completeness
Check:
- Does the workflow achieve the user's stated objective?
- Does every required operation have an appropriate node?
- Are connections logically consistent?
- Does each execution path reach an appropriate outcome?
- Are there missing steps between dependent operations?

## Evidence-Based Review
For every issue:
- Identify the affected requirement ID
- Identify relevant node/edge IDs
- Explain what is missing or incorrect
- Explain why it doesn't satisfy the requirement
- Suggest the correction

Never invent node IDs. Do not claim a missing operation exists.

## Response Format
Return ONLY valid JSON (no markdown fences) with this exact structure:
{{
  "status": "passed" or "failed" or "needs_clarification",
  "summary": "Brief assessment",
  "requirement_coverage": [
    {{
      "requirement_id": "R1",
      "description": "What this requirement asks for",
      "status": "covered" or "partially_covered" or "missing" or "unclear",
      "evidence": ["node_id_1"],
      "explanation": "Why this status"
    }}
  ],
  "issues": [
    {{
      "issue_type": "missing_operation",
      "severity": "high",
      "requirement_id": "R1",
      "affected_node_ids": [],
      "affected_edge_ids": [],
      "description": "What is wrong",
      "suggested_correction": "How to fix"
    }}
  ],
  "assumptions": [],
  "clarification_required": false
}}

Rules:
- Status must be "passed" only if ALL mandatory requirements are "covered".
- If any mandatory requirement is "missing" or "partially_covered", status must be "failed".
- Use "needs_clarification" when the requirement is too ambiguous to audit confidently.
- Do not use numeric confidence scores.
- Do not approve just because JSON structure is valid.
"""


REVIEWER_SYSTEM_PROMPT = build_reviewer_system_prompt()


class WorkflowReviewer:
    """Reviews a validated WorkflowSchema against the original user prompt using gemma-4-31b-it."""

    def __init__(
        self,
        llm_service: LLMService,
        registry: Optional[NodeRegistry] = None,
    ) -> None:
        self._llm_service = llm_service
        self._registry = registry or get_default_registry()
        self._reviewer_system_prompt = build_reviewer_system_prompt(self._registry)

    def review(self, original_prompt: str, workflow: WorkflowSchema) -> WorkflowReview:
        """Run an independent semantic review and return structured feedback."""
        review_prompt = (
            f"Original User Requirement:\n{original_prompt}\n\n"
            f"Generated Workflow JSON:\n{workflow.model_dump_json(indent=2)}"
        )
        try:
            raw_response = self._llm_service.generate_review_json(
                system_prompt=self._reviewer_system_prompt,
                user_prompt=review_prompt,
                temperature=0.1,
            )
        except Exception as exc:
            logger.error("Reviewer LLM call failed: %s", exc)
            # Never treat a failed API call as a successful review
            return WorkflowReview(
                status=ReviewStatus.FAILED,
                summary=f"Reviewer API call failed: {exc}",
                issues=[],
                requirement_coverage=[],
                clarification_required=False,
            )

        try:
            data = json.loads(raw_response)
            return WorkflowReview.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Failed to parse workflow review output: %s", exc)
            # Never assume passed on parse failure
            return WorkflowReview(
                status=ReviewStatus.FAILED,
                summary=f"Review response could not be parsed: {exc}",
                issues=[],
                requirement_coverage=[],
                clarification_required=False,
            )
