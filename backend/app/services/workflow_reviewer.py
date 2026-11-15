"""LLM-based Workflow Reviewer (Semantic Auditor).

Uses gemma-4-31b-it via a dedicated LLM call to independently verify
the logical correctness and completeness of generated workflows.
"""

import json
import logging

from typing import List, Optional
from pydantic import ValidationError

from app.core.errors import ErrorCategory
from app.engine.planner import plan_workflow
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.review import ReviewIssue, ReviewStatus, WorkflowReview
from app.schemas.workflow import WorkflowSchema
from app.services.llm_errors import classify_llm_error
from app.services.llm_service import LLMGenerationError, LLMService
from app.services.workflow_upgrade import upgrade_workflow

_PLANNER_CATEGORY = {
    ErrorCategory.UNSUPPORTED_CAPABILITY: "capability",
    ErrorCategory.SCHEMA_VALIDATION: "schema",
    ErrorCategory.INVALID_MAPPING: "feasibility",
    ErrorCategory.GRAPH_VALIDATION: "feasibility",
    ErrorCategory.MISSING_CREDENTIALS: "security",
}

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
- Does every node use an operation listed in the Node Registry above? Operations that are not listed do NOT
  exist and cannot run: report them as `capability` issues. Never assume a capability that is not listed.
- Does each node's config follow its operation's config example shape (keys, types)?
- Are required input/output dependencies represented, and do {{{{nodes.<id>.output...}}}} references point to
  nodes that run before the referencing node?
- Are there unnecessary or unrelated nodes?

## Triggers, Branches and Data References
Check:
- Is there exactly one trigger, and is it the right kind for the requirement (manual, webhook, form, schedule)?
- Do branch edges use the operation's real output ports (true/false for If, case keys/default for Switch)?
- Does every data reference use an existing upstream node id and a plausible output field?

## Security and Permissions
Check:
- Are secrets placed in plain config values (API keys, passwords, tokens) instead of credential references?
- Does the workflow send data to external endpoints the user did not ask for?
- Do AI Agent nodes get only the tools the task needs?

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
      "category": "logic" or "schema" or "capability" or "feasibility" or "security",
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
- The user message includes DETERMINISTIC VALIDATION FACTS produced by the execution planner. They are
  authoritative: if they list errors, status must be "failed" and each error must appear as an issue with the
  matching category. Do not contradict them and do not invent capabilities they do not mention.
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

    def _plan_facts(self, workflow: WorkflowSchema) -> List[ReviewIssue]:
        """Deterministic planner findings (capability, schema, feasibility), independent of the LLM."""
        try:
            plan = plan_workflow(upgrade_workflow(workflow, self._registry), self._registry)
        except Exception as exc:  # never let the deterministic check crash the review
            logger.warning("Planner facts unavailable for review: %s", exc)
            return []
        facts: List[ReviewIssue] = []
        for issue in plan.errors:
            facts.append(ReviewIssue(
                issue_type=f"planner_{issue.category.value.lower()}",
                severity="high",
                category=_PLANNER_CATEGORY.get(issue.category, "feasibility"),
                affected_node_ids=[issue.node_id] if issue.node_id else [],
                affected_edge_ids=[issue.edge_id] if issue.edge_id else [],
                description=issue.message,
                suggested_correction=issue.suggestion or "",
            ))
        return facts

    def review(self, original_prompt: str, workflow: WorkflowSchema) -> WorkflowReview:
        """Run an independent semantic review and return structured feedback.

        The LLM judges logical correctness; the deterministic planner judges schema validity, capability
        availability and execution feasibility. A workflow the planner rejects can never be "passed".
        """
        facts = self._plan_facts(workflow)
        facts_text = "\n".join(f"- [{f.category}] {f.description}" for f in facts) or "- none (the planner found no errors)"
        review_prompt = (
            f"Original User Requirement:\n{original_prompt}\n\n"
            f"Generated Workflow JSON:\n{workflow.model_dump_json(indent=2)}\n\n"
            f"DETERMINISTIC VALIDATION FACTS (execution planner):\n{facts_text}"
        )
        review = self._llm_review(review_prompt)
        return self._enforce_facts(review, facts)

    @staticmethod
    def _enforce_facts(review: WorkflowReview, facts: List[ReviewIssue]) -> WorkflowReview:
        if not facts:
            return review
        known = {(i.description or "").strip() for i in review.issues}
        merged = list(review.issues) + [f for f in facts if f.description.strip() not in known]
        status = review.status
        summary = review.summary
        if status == ReviewStatus.PASSED:
            status = ReviewStatus.FAILED
            summary = (f"{summary} " if summary else "") + (
                f"Overridden to failed: the execution planner reported {len(facts)} blocking problem(s).")
        return review.model_copy(update={"issues": merged, "status": status, "summary": summary})

    def _llm_review(self, review_prompt: str) -> WorkflowReview:
        try:
            raw_response = self._llm_service.generate_review_json(
                system_prompt=self._reviewer_system_prompt,
                user_prompt=review_prompt,
                temperature=0.1,
            )
        except Exception as exc:
            info = classify_llm_error(exc)
            logger.error("Reviewer LLM call failed: [%s] %s", info.category, info.message)
            # Never treat a failed API call as a successful review
            return WorkflowReview(
                status=ReviewStatus.FAILED,
                summary=f"Reviewer API call failed: {exc if isinstance(exc, LLMGenerationError) else info.message} "
                        f"{info.suggestion}",
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
