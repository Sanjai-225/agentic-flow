"""Canonical workflow schema (v2) shared by the AI designer, the editor and the execution engine.

Schema v2 evolves the original v1 design schema in place:
- ``operation`` is the stable, registry-resolved executable identifier.
- ``type`` is the legacy/design type kept for AI-designer compatibility.
- ``inputs`` holds named input mappings (literals or ``{{...}}`` references).
- Edges carry ``source_port``/``target_port`` for control-flow routing.
- ``ui`` blocks hold presentation-only metadata the engine never reads.

v1 documents (no ``schema_version``) still validate; ``app.services.workflow_upgrade``
maps them onto registry operations.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CANONICAL_SCHEMA_VERSION = 2


class ToolSchema(BaseModel):
    """External tool or integration associated with a workflow node (legacy design metadata)."""

    name: str = Field(..., min_length=1, description="Name of the external tool or service.")
    operation: str = Field(..., min_length=1, description="Action or operation performed by the tool.")
    status: str = Field(
        default="not_connected",
        description="Connection status of the tool (design-only workflows default to not_connected).",
    )


class NodePosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class NodeUI(BaseModel):
    """Presentation-only metadata. Never read by the execution engine."""

    position: Optional[NodePosition] = None
    color: Optional[str] = None


class RetryPolicy(BaseModel):
    """Bounded retry policy with exponential backoff."""

    max_attempts: int = Field(default=1, ge=1, le=10, description="Total attempts including the first.")
    backoff_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    max_backoff_seconds: float = Field(default=30.0, ge=0.0, le=300.0)


class NodeSchema(BaseModel):
    """A single node in the canonical workflow graph."""

    id: str = Field(..., min_length=1, description="Unique, stable node identifier.")
    type: str = Field(default="", description="Legacy/design node type (open-ended).")
    operation: Optional[str] = Field(
        default=None,
        description="Registry operation id. 'unsupported:<type>' marks a non-executable design node.",
    )
    type_version: int = Field(default=1, ge=1)
    label: str = Field(..., min_length=1, description="Human-readable node label.")
    description: str = Field(default="", description="Detailed explanation of what this node does.")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Node configuration validated against the registry config model.",
    )
    inputs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named input mappings: literal values or {{...}} reference expressions.",
    )
    retry: Optional[RetryPolicy] = None
    timeout_seconds: Optional[float] = Field(default=None, gt=0, le=3600)
    on_error: Literal["fail", "continue"] = "fail"
    tool: Optional[ToolSchema] = Field(
        default=None,
        description="Optional legacy design metadata describing an external tool.",
    )
    ui: NodeUI = Field(default_factory=NodeUI)

    @field_validator("id", "label")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped

    @model_validator(mode="after")
    def _type_or_operation(self) -> "NodeSchema":
        self.type = (self.type or "").strip()
        if self.operation is not None:
            self.operation = self.operation.strip() or None
        if not self.type and not self.operation:
            raise ValueError(f"Node '{self.id}' must define 'operation' (or legacy 'type').")
        if not self.type and self.operation:
            self.type = self.operation
        return self


class EdgeSchema(BaseModel):
    """Directed connection between two workflow nodes."""

    id: str = Field(..., min_length=1, description="Unique edge identifier.")
    source: str = Field(..., min_length=1, description="Source node ID.")
    target: str = Field(..., min_length=1, description="Target node ID.")
    source_port: str = Field(default="main", description="Output port on the source node (If: 'true'/'false').")
    target_port: str = Field(default="main", description="Input port on the target node.")
    label: Optional[str] = Field(default=None, description="Optional edge label.")
    condition: Optional[str] = Field(default=None, description="Legacy free-text branching condition.")

    @field_validator("id", "source", "target")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field must not be empty or whitespace.")
        return stripped

    @field_validator("source_port", "target_port", mode="before")
    @classmethod
    def _default_port(cls, value: Optional[str]) -> str:
        return (value or "main").strip() or "main"


class WorkflowSettings(BaseModel):
    default_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)


class WorkflowSchema(BaseModel):
    """Complete canonical workflow definition."""

    schema_version: int = Field(default=CANONICAL_SCHEMA_VERSION, ge=1)
    workflow_id: str = Field(..., min_length=1, description="Unique workflow identifier.")
    version: int = Field(default=1, ge=1, description="Saved definition version.")
    workflow_name: str = Field(..., min_length=1, description="Human-readable workflow name.")
    description: str = Field(default="", description="High-level workflow summary.")
    nodes: List[NodeSchema] = Field(..., min_length=1, description="List of workflow nodes.")
    edges: List[EdgeSchema] = Field(default_factory=list, description="List of directed edges.")
    start_nodes: List[str] = Field(
        default_factory=list, description="Entry-point node IDs (derived from the graph when omitted)."
    )
    end_nodes: List[str] = Field(
        default_factory=list, description="Terminal node IDs (derived from the graph when omitted)."
    )
    settings: WorkflowSettings = Field(default_factory=WorkflowSettings)
    ui: Dict[str, Any] = Field(default_factory=dict, description="Presentation-only metadata (viewport).")

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

        # Derive entry/terminal nodes from topology when not supplied.
        if not self.start_nodes:
            targets = {edge.target for edge in self.edges}
            self.start_nodes = [n.id for n in self.nodes if n.id not in targets]
        if not self.end_nodes:
            sources = {edge.source for edge in self.edges}
            self.end_nodes = [n.id for n in self.nodes if n.id not in sources]

        for start_id in self.start_nodes:
            if start_id not in node_ids:
                raise ValueError(f"start_nodes references unknown node '{start_id}'.")

        for end_id in self.end_nodes:
            if end_id not in node_ids:
                raise ValueError(f"end_nodes references unknown node '{end_id}'.")

        return self

    def get_node(self, node_id: str) -> Optional[NodeSchema]:
        return next((n for n in self.nodes if n.id == node_id), None)


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
