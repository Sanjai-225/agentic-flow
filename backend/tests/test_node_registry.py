"""Unit tests for Phase 3 — Node Registry, node catalog discovery, and LLM prompt integration."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.registry import (
    NodeCategory,
    NodeDefinition,
    PortDataType,
    PortDefinition,
    PortType,
    ToolDefinition,
)
from app.services.llm_service import (
    LLMService,
    WORKFLOW_ARCHITECT_SYSTEM_PROMPT,
    build_architect_system_prompt,
)
from app.services.workflow_reviewer import (
    REVIEWER_SYSTEM_PROMPT,
    build_reviewer_system_prompt,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def registry() -> NodeRegistry:
    return get_default_registry()


# -------------------------------------------------------------------
# 1. Registry Content & Coverage Tests
# -------------------------------------------------------------------

def test_registry_has_standard_nodes(registry: NodeRegistry):
    """Verify registry is populated with standard nodes across all domains."""
    all_nodes = registry.list_all()
    assert len(all_nodes) >= 20, f"Expected at least 20 nodes, got {len(all_nodes)}"

    # Check key node types exist
    expected_types = [
        "webhook_trigger",
        "schedule_trigger",
        "email_trigger",
        "manual_trigger",
        "email_output",
        "notification_output",
        "webhook_output",
        "llm_agent",
        "text_classifier",
        "entity_extractor",
        "summarizer",
        "api_call",
        "database_query",
        "database_update",
        "file_operation",
        "tool_integration",
        "condition",
        "switch",
        "loop",
        "error_handler",
        "data_transform",
        "filter",
        "code_execution",
        "vector_search",
        "knowledge_retrieval",
        "human_approval",
    ]
    for ntype in expected_types:
        node = registry.get(ntype)
        assert node is not None, f"Expected standard node type '{ntype}' in registry"
        assert node.node_type == ntype
        assert len(node.label) > 0
        assert len(node.description) > 0


def test_registry_covers_all_categories(registry: NodeRegistry):
    """Verify registry covers all 7 node categories defined in roadmap."""
    categories = registry.get_categories()
    expected_categories = {
        NodeCategory.INPUT_OUTPUT.value,
        NodeCategory.AI_AGENT.value,
        NodeCategory.TOOLS.value,
        NodeCategory.LOGIC.value,
        NodeCategory.DATA_PROCESSING.value,
        NodeCategory.MEMORY_KNOWLEDGE.value,
        NodeCategory.HUMAN_IN_THE_LOOP.value,
    }
    assert expected_categories.issubset(set(categories)), f"Missing categories: {expected_categories - set(categories)}"


def test_registry_filter_by_category(registry: NodeRegistry):
    """Verify category filtering returns only matching node definitions."""
    ai_nodes = registry.list_by_category(NodeCategory.AI_AGENT)
    assert len(ai_nodes) >= 4
    for n in ai_nodes:
        assert n.category == NodeCategory.AI_AGENT

    logic_nodes = registry.list_by_category("logic")
    assert len(logic_nodes) >= 4
    for n in logic_nodes:
        assert n.category == NodeCategory.LOGIC


def test_registry_lookup_case_insensitivity(registry: NodeRegistry):
    """Verify registry lookup handles whitespace and mixed case gracefully."""
    assert registry.get("LLM_AGENT") is not None
    assert registry.get("  webhook_trigger  ") is not None
    assert registry.get("Non_Existent_Node_Type") is None


def test_registry_ports_and_tools_semantics(registry: NodeRegistry):
    """Verify node definitions have typed input/output ports and tool metadata."""
    cond_node = registry.get("condition")
    assert cond_node is not None
    assert len(cond_node.inputs) >= 1
    assert len(cond_node.outputs) >= 2  # True/False branches

    approval_node = registry.get("human_approval")
    assert approval_node is not None
    assert approval_node.category == NodeCategory.HUMAN_IN_THE_LOOP
    assert len(approval_node.compatible_tools) >= 1
    tool_names = [t.name for t in approval_node.compatible_tools]
    assert "Slack" in tool_names or "Email" in tool_names

    email_trigger = registry.get("email_trigger")
    assert email_trigger is not None
    assert len(email_trigger.outputs) >= 1


def test_custom_node_registration():
    """Verify ability to dynamically register new node definitions."""
    custom_reg = NodeRegistry()
    custom_node = NodeDefinition(
        node_type="custom_voice_transcriber",
        label="Voice Transcriber",
        category=NodeCategory.AI_AGENT,
        description="Transcribes audio streams into text transcripts.",
        inputs=[PortDefinition(id="in_audio", name="Audio Stream", port_type=PortType.INPUT, data_type=PortDataType.FILE)],
        outputs=[PortDefinition(id="out_text", name="Transcript", port_type=PortType.OUTPUT, data_type=PortDataType.STRING)],
    )
    custom_reg.register(custom_node)
    assert custom_reg.get("custom_voice_transcriber") == custom_node
    assert len(custom_reg.list_all()) == 1


# -------------------------------------------------------------------
# 2. LLM Prompt Knowledge Injection Tests
# -------------------------------------------------------------------

def test_catalog_formatting_for_prompt(registry: NodeRegistry):
    """Verify formatted catalog for LLM contains structured category blocks and types."""
    catalog_text = registry.get_catalog_for_prompt()
    assert "STANDARD NODE REGISTRY" in catalog_text
    assert "webhook_trigger" in catalog_text
    assert "llm_agent" in catalog_text
    assert "human_approval" in catalog_text
    assert "Compatible tools:" in catalog_text
    assert "REGISTRY USAGE RULES:" in catalog_text


def test_architect_system_prompt_includes_registry():
    """Verify WORKFLOW_ARCHITECT_SYSTEM_PROMPT includes live node catalog."""
    prompt = build_architect_system_prompt()
    assert "STANDARD NODE REGISTRY" in prompt
    assert "webhook_trigger" in prompt
    assert "llm_agent" in prompt
    assert "database_query" in prompt
    assert "Select matching node types from the standard Node Registry" in prompt
    # Also verify global variable has it
    assert "STANDARD NODE REGISTRY" in WORKFLOW_ARCHITECT_SYSTEM_PROMPT


def test_reviewer_system_prompt_includes_registry():
    """Verify REVIEWER_SYSTEM_PROMPT is enriched with node registry specifications."""
    prompt = build_reviewer_system_prompt()
    assert "STANDARD NODE REGISTRY" in prompt
    assert "Operation Correctness & Node Registry Alignment" in prompt
    assert "REVIEWER_SYSTEM_PROMPT" is not None
    assert "STANDARD NODE REGISTRY" in REVIEWER_SYSTEM_PROMPT


# -------------------------------------------------------------------
# 3. Node Registry API Endpoints Tests
# -------------------------------------------------------------------

def test_api_list_categories(client: TestClient):
    """GET /api/registry/categories should return all distinct categories."""
    response = client.get("/api/registry/categories")
    assert response.status_code == 200
    categories = response.json()
    assert isinstance(categories, list)
    assert len(categories) >= 7
    assert "ai_agent" in categories
    assert "tools" in categories


def test_api_list_nodes_all(client: TestClient):
    """GET /api/registry/nodes should return catalog with all registered nodes."""
    response = client.get("/api/registry/nodes")
    assert response.status_code == 200
    data = response.json()
    assert "total_nodes" in data
    assert "categories" in data
    assert "nodes" in data
    assert data["total_nodes"] >= 20
    assert len(data["nodes"]) == data["total_nodes"]


def test_api_list_nodes_filtered_by_category(client: TestClient):
    """GET /api/registry/nodes?category=logic should return only logic nodes."""
    response = client.get("/api/registry/nodes?category=logic")
    assert response.status_code == 200
    data = response.json()
    assert data["total_nodes"] >= 4
    for node in data["nodes"]:
        assert node["category"] == "logic"


def test_api_get_specific_node(client: TestClient):
    """GET /api/registry/nodes/{node_type} should return specific node definition."""
    response = client.get("/api/registry/nodes/llm_agent")
    assert response.status_code == 200
    node = response.json()
    assert node["node_type"] == "llm_agent"
    assert node["category"] == "ai_agent"
    assert len(node["inputs"]) >= 1
    assert len(node["outputs"]) >= 1


def test_api_get_unknown_node_404(client: TestClient):
    """GET /api/registry/nodes/{node_type} with unknown type should return 404."""
    response = client.get("/api/registry/nodes/quantum_teleportation_node")
    assert response.status_code == 404
    detail = response.json().get("detail", "")
    assert "not found" in detail.lower()
