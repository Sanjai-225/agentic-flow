"""Pydantic schemas for the workflow semantic review system."""

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


class ReviewStatus(str, Enum):
    """Overall review verdict."""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_CLARIFICATION = "needs_clarification"


class RequirementStatus(str, Enum):
    """Coverage status for a single requirement."""

    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    MISSING = "missing"
    UNCLEAR = "unclear"


class RequirementCoverage(BaseModel):
    """Coverage assessment for one identified requirement."""

    requirement_id: str = Field(..., description="Identifier for this requirement (e.g., R1, R2).")
    description: str = Field(default="", description="What this requirement asks for.")
    status: RequirementStatus = Field(..., description="Coverage status.")
    evidence: List[str] = Field(default_factory=list, description="Node IDs that implement this requirement.")
    explanation: str = Field(default="", description="Why this status was assigned.")


class ReviewIssue(BaseModel):
    """A single issue identified during semantic review."""

    issue_type: str = Field(
        ...,
        description=(
            "Type of issue: missing_operation, incorrect_connection, missing_condition, "
            "unnecessary_operation, incorrect_tool, contradictory_logic."
        ),
    )
    severity: str = Field(..., description="high, medium, or low.")
    requirement_id: str = Field(default="", description="Related requirement ID if applicable.")
    affected_node_ids: List[str] = Field(default_factory=list)
    affected_edge_ids: List[str] = Field(default_factory=list)
    description: str = Field(..., description="What is wrong.")
    suggested_correction: str = Field(default="", description="How to fix it.")


class WorkflowReview(BaseModel):
    """Complete structured review report from the semantic auditor."""

    status: ReviewStatus = Field(..., description="Overall review verdict.")
    summary: str = Field(default="", description="Brief assessment of the workflow.")
    requirement_coverage: List[RequirementCoverage] = Field(default_factory=list)
    issues: List[ReviewIssue] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    clarification_required: bool = Field(default=False)

    @field_validator("assumptions", mode="before")
    @classmethod
    def _normalize_assumptions(cls, v: Any) -> List[str]:
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                result.append(item.get("description") or item.get("text") or str(item))
            else:
                result.append(str(item))
        return result
