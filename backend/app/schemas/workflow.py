"""Pydantic schemas for workflow generation, validation, and review."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ToolSchema(BaseModel):
    """External tool or integration associated with a workflow node."""

    name: str = Field(..., min_length=1, description="Name of the external tool or service.")
    operation: str = Field(..., min_length=1, description="Action or operation performed by the tool.")
    status: str = Field(
        default="not_connected",
        description="Connection status of the tool (design-only workflows default to not_connected).",
    )


class NodeSchema(BaseModel):
    """A single node in the generated workflow graph.

    Node types are intentionally open-ended strings rather than a fixed enum so
    the LLM can choose the most appropriate node types for any domain.
    """

    id: str = Field(..., min_length=1, description="Unique node identifier.")
    type: str = Field(..., min_length=1, description="Dynamic node type determined by the architect.")
    label: str = Field(..., min_length=1, description="Human-readable node label.")
    description: str = Field(default="", description="Detailed explanation of what this node does.")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Flexible node-specific configuration parameters.",
    )
    tool: Optional[ToolSchema] = Field(
        default=None,
        description="Optional external tool or integration used by this node.",
    )

    @field_validator("id", "type", "label")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped


class EdgeSchema(BaseModel):
    """Directed connection between two workflow nodes."""

    id: str = Field(..., min_length=1, description="Unique edge identifier.")
    source: str = Field(..., min_length=1, description="Source node ID.")
    target: str = Field(..., min_length=1, description="Target node ID.")
    label: Optional[str] = Field(default=None, description="Optional edge label.")
    condition: Optional[str] = Field(default=None, description="Optional branching condition.")

    @field_validator("id", "source", "target")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped


class WorkflowSchema(BaseModel):
    """Complete workflow definition returned by the API."""

    workflow_id: str = Field(..., min_length=1, description="Unique workflow identifier.")
    workflow_name: str = Field(..., min_length=1, description="Human-readable workflow name.")
    description: str = Field(default="", description="High-level workflow summary.")
    nodes: List[NodeSchema] = Field(..., min_length=1, description="List of workflow nodes.")
    edges: List[EdgeSchema] = Field(default_factory=list, description="List of directed edges.")
    start_nodes: List[str] = Field(..., min_length=1, description="IDs of entry-point nodes.")
    end_nodes: List[str] = Field(..., min_length=1, description="IDs of terminal nodes.")

    @field_validator("workflow_id", "workflow_name")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped

    @model_validator(mode="after")
    def _validate_references_and_uniqueness(self) -> "WorkflowSchema":
        node_ids: set[str] = set()
        for node in self.nodes:
            if node.id in node_ids:
                raise ValueError(f"Duplicate node id: '{node.id}'.")
            node_ids.add(node.id)

        edge_ids: set[str] = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                raise ValueError(f"Duplicate edge id: '{edge.id}'.")
            edge_ids.add(edge.id)

            if edge.source not in node_ids:
                raise ValueError(f"Edge '{edge.id}' references unknown source node '{edge.source}'.")
            if edge.target not in node_ids:
                raise ValueError(f"Edge '{edge.id}' references unknown target node '{edge.target}'.")

        for start_id in self.start_nodes:
            if start_id not in node_ids:
                raise ValueError(f"start_nodes references unknown node '{start_id}'.")

        for end_id in self.end_nodes:
            if end_id not in node_ids:
                raise ValueError(f"end_nodes references unknown node '{end_id}'.")

        return self


class GenerateWorkflowRequest(BaseModel):
    """Request payload for POST /api/workflows/generate."""

    prompt: str = Field(..., min_length=3, description="Natural-language workflow requirement.")
    review: Optional[bool] = Field(
        default=None,
        description="Optional override to enable or disable LLM self-review.",
    )

    @field_validator("prompt")
    @classmethod
    def _strip_prompt(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("Prompt must be at least 3 non-whitespace characters.")
        return stripped


class WorkflowReviewResult(BaseModel):
    """Structured output from the LLM workflow self-reviewer."""

    passed: bool = Field(..., description="Whether the workflow satisfies the original requirements.")
    coverage_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Estimated requirement coverage from 0.0 to 1.0.",
    )
    missing_requirements: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    summary: str = Field(default="")
