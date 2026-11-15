"""Pydantic schemas for the Node Registry system (Phase 3)."""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.schemas.workflow import RetryPolicy


class NodeCategory(str, Enum):
    """Primary category classifications for workflow nodes."""

    INPUT_OUTPUT = "input_output"
    AI_AGENT = "ai_agent"
    TOOLS = "tools"
    LOGIC = "logic"
    DATA_PROCESSING = "data_processing"
    MEMORY_KNOWLEDGE = "memory_knowledge"
    HUMAN_IN_THE_LOOP = "human_in_the_loop"


class PortType(str, Enum):
    """Direction of a connection port."""

    INPUT = "input"
    OUTPUT = "output"


class PortDataType(str, Enum):
    """Data type carried through a port."""

    ANY = "any"
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    FILE = "file"


class PortDefinition(BaseModel):
    """Defines an input or output connection port on a node."""

    id: str = Field(..., description="Unique identifier of the port within the node.")
    name: str = Field(..., description="Human-readable port label.")
    port_type: PortType = Field(..., description="'input' or 'output'.")
    data_type: PortDataType = Field(default=PortDataType.ANY, description="Expected payload type.")
    description: str = Field(default="", description="Description of the data passed through this port.")
    required: bool = Field(default=True, description="Whether this port must be connected.")


class ToolDefinition(BaseModel):
    """Specification of an external tool or service operation supported by a node."""

    name: str = Field(..., description="Tool or service name (e.g., 'Gmail', 'Slack', 'PostgreSQL').")
    operation: str = Field(..., description="Specific action performed (e.g., 'send_email', 'query_table').")
    description: str = Field(default="", description="What this operation does.")
    required_params: List[str] = Field(default_factory=list, description="Mandatory configuration keys.")
    optional_params: List[str] = Field(default_factory=list, description="Optional configuration keys.")


ConfigWidget = Literal[
    "text",
    "textarea",
    "expression",
    "number",
    "boolean",
    "select",
    "json",
    "keyvalue",
    "conditions",
    "set_fields",
    "credential",
]


class ConfigField(BaseModel):
    """UI hint describing how the editor renders one configuration field."""

    key: str = Field(..., description="Dot path into the node config (e.g. 'auth.type').")
    label: str
    widget: ConfigWidget = "text"
    required: bool = False
    options: List[str] = Field(default_factory=list, description="Choices for 'select' widgets.")
    placeholder: Optional[str] = None
    help: Optional[str] = None
    supports_expressions: bool = Field(default=False, description="Whether {{...}} references are allowed.")
    show_if: Optional[Dict[str, List[str]]] = Field(
        default=None, description="Render only when another field has one of the listed values."
    )


class NodeDefinition(BaseModel):
    """Canonical definition of a reusable workflow node type in the registry."""

    node_type: str = Field(..., min_length=1, description="Unique snake_case identifier (e.g. 'webhook_trigger', 'llm_agent').")
    label: str = Field(..., min_length=1, description="User-facing display name.")
    category: NodeCategory = Field(..., description="Functional group of this node.")
    description: str = Field(..., description="Detailed description of the node's function and purpose.")
    inputs: List[PortDefinition] = Field(default_factory=list, description="Input ports accepted by this node.")
    outputs: List[PortDefinition] = Field(default_factory=list, description="Output ports produced by this node.")
    default_config: Dict[str, Any] = Field(default_factory=dict, description="Default configuration schema/values.")
    compatible_tools: List[ToolDefinition] = Field(default_factory=list, description="Tools/services this node works with.")
    icon: Optional[str] = Field(default=None, description="Icon identifier for frontend rendering.")
    tags: List[str] = Field(default_factory=list, description="Searchable tags (e.g. ['email', 'trigger', 'google']).")

    # --- Execution metadata (Milestone 1) ---
    operation_id: str = Field(
        default="",
        description="Stable operation identifier used by canonical workflows (defaults to node_type).",
    )
    version: int = Field(default=1, ge=1)
    executable: bool = Field(default=False, description="True only when a registered executor implements it.")
    status: Literal["ready", "design_only", "needs_config"] = "design_only"
    aliases: List[str] = Field(default_factory=list, description="Legacy design types mapped to this operation.")
    is_trigger: bool = False
    ports_in: List[str] = Field(default_factory=lambda: ["main"], description="Routing input ports.")
    ports_out: List[str] = Field(default_factory=lambda: ["main"], description="Routing output ports.")
    config_model: Optional[Type[BaseModel]] = Field(default=None, exclude=True)
    ui_fields: List[ConfigField] = Field(default_factory=list)
    lazy_config_fields: List[str] = Field(
        default_factory=list, description="Config fields the executor resolves itself (e.g. per item)."
    )
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="Description of accepted input data.")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="Description of produced output.")
    credentials: List[str] = Field(default_factory=list, description="Credential types this node may require.")
    side_effects: bool = False
    idempotent: bool = True
    requires_approval: bool = False
    supports_streaming: bool = False
    is_async: bool = False
    default_retry: RetryPolicy = Field(default_factory=RetryPolicy)
    default_timeout_seconds: float = Field(default=60.0, gt=0, le=3600)

    @field_validator("node_type")
    @classmethod
    def _validate_node_type(cls, v: str) -> str:
        stripped = v.strip().lower()
        if not stripped:
            raise ValueError("node_type must not be empty.")
        return stripped

    @model_validator(mode="after")
    def _default_operation_id(self) -> "NodeDefinition":
        if not self.operation_id:
            self.operation_id = self.node_type
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def config_schema(self) -> Dict[str, Any]:
        """JSON Schema of the configuration model (empty for design-only nodes)."""
        return self.config_model.model_json_schema() if self.config_model else {}


class RegistryCatalogResponse(BaseModel):
    """API response model for the node catalog."""

    total_nodes: int = Field(..., description="Total number of registered node types.")
    categories: List[str] = Field(..., description="Available node categories.")
    nodes: List[NodeDefinition] = Field(..., description="List of registered node definitions.")
