"""Pydantic schemas for the Node Registry system (Phase 3)."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


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

    @field_validator("node_type")
    @classmethod
    def _validate_node_type(cls, v: str) -> str:
        stripped = v.strip().lower()
        if not stripped:
            raise ValueError("node_type must not be empty.")
        return stripped


class RegistryCatalogResponse(BaseModel):
    """API response model for the node catalog."""

    total_nodes: int = Field(..., description="Total number of registered node types.")
    categories: List[str] = Field(..., description="Available node categories.")
    nodes: List[NodeDefinition] = Field(..., description="List of registered node definitions.")
