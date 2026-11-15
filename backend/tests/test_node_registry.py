"""Node Registry: active library contents, lookups, prompt integration and API endpoints.

Milestone 2 removed every design-only type from the active library (see
docs/NODE_CATALOGUE.md). These tests pin that contract: the registry exposes
only executable operations, and removed types are identifiable through
``app.registry.legacy`` but never registered.
"""

import pytest
from fastapi.testclient import TestClient

from app.executors import get_executor
from app.main import app
from app.registry.legacy import LEGACY_NODE_TYPES
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.registry import (
    NodeCategory,
    NodeDefinition,
    PortDataType,
    PortDefinition,
    PortType,
)
from app.services.llm_service import (
    WORKFLOW_ARCHITECT_SYSTEM_PROMPT,
    build_architect_system_prompt,
)
from app.services.workflow_reviewer import (
    REVIEWER_SYSTEM_PROMPT,
    build_reviewer_system_prompt,
)

MILESTONE_1_OPERATIONS = {
    "core.manual_trigger", "core.webhook_trigger", "core.set", "core.json_parse", "core.filter",
    "core.if", "core.transform", "core.end", "http.request",
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def registry() -> NodeRegistry:
    return get_default_registry()


# -------------------------------------------------------------------
# 1. Registry content
# -------------------------------------------------------------------

def test_active_library_contains_only_executable_operations(registry: NodeRegistry):
    nodes = registry.list_all()
    assert nodes, "registry must not be empty"
    for node in nodes:
        assert node.executable is True and node.status == "ready", node.operation_id
        assert get_executor(node.operation_id) is not None, node.operation_id
    assert MILESTONE_1_OPERATIONS <= {n.operation_id for n in nodes}


def test_removed_design_only_types_are_not_registered(registry: NodeRegistry):
    assert len(LEGACY_NODE_TYPES) == 24
    for legacy in LEGACY_NODE_TYPES:
        definition = registry.get(legacy)
        # A removed type may only resolve to a *different* executable operation through an explicit alias
        # of an executable definition; it must never resolve to a design-only definition.
        assert definition is None or definition.executable, legacy
        assert registry.get_operation(legacy) is None, legacy


def test_legacy_aliases_of_milestone_1_operations_still_resolve(registry: NodeRegistry):
    """Older design types that were already superseded in Milestone 1 keep resolving (v1 upgrade path)."""
    expected = {"manual_trigger": "core.manual_trigger", "webhook_trigger": "core.webhook_trigger",
                "data_transform": "core.transform", "filter": "core.filter", "condition": "core.if",
                "api_call": "http.request"}
    for node_type, op in expected.items():
        assert registry.get(node_type).operation_id == op


def test_registry_filter_by_category(registry: NodeRegistry):
    logic_nodes = registry.list_by_category("logic")
    assert {"core.if", "core.end"} <= {n.operation_id for n in logic_nodes}
    for n in logic_nodes:
        assert n.category == NodeCategory.LOGIC
    for n in registry.list_by_category(NodeCategory.DATA_PROCESSING):
        assert n.category == NodeCategory.DATA_PROCESSING


def test_registry_lookup_case_insensitivity(registry: NodeRegistry):
    assert registry.get("CORE.SET") is not None
    assert registry.get("  webhook_trigger  ") is not None
    assert registry.get("Non_Existent_Node_Type") is None


def test_branching_ports(registry: NodeRegistry):
    assert registry.get("condition").ports_out == ["true", "false"]
    assert registry.get_operation("core.end").ports_out == []


def test_custom_node_registration():
    """The registry stays extensible: later milestones add definitions without engine changes."""
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
# 2. LLM prompt knowledge injection
# -------------------------------------------------------------------

def test_catalog_formatting_for_prompt(registry: NodeRegistry):
    catalog_text = registry.get_catalog_for_prompt()
    assert "STANDARD NODE REGISTRY" in catalog_text
    assert "REGISTRY USAGE RULES:" in catalog_text
    for node in registry.list_all():
        assert f"`{node.operation_id}`" in catalog_text
        assert f"`{node.id_prefix}_1`" in catalog_text
    # Removed types and design-only concepts are not advertised.
    for legacy in ["llm_agent", "human_approval", "database_query", "code_execution", "vector_search"]:
        assert f"`{legacy}`" not in catalog_text
    assert "DESIGN-ONLY" not in catalog_text and "not_connected" not in catalog_text


def test_architect_system_prompt_includes_registry():
    prompt = build_architect_system_prompt()
    assert "STANDARD NODE REGISTRY" in prompt
    assert "core.webhook_trigger" in prompt
    assert "Never invent node types" in prompt
    for legacy in ["llm_agent", "database_query", "email_trigger", "code_execution"]:
        assert f"`{legacy}`" not in prompt
    assert "not_connected" not in prompt
    assert "STANDARD NODE REGISTRY" in WORKFLOW_ARCHITECT_SYSTEM_PROMPT


def test_reviewer_system_prompt_includes_registry():
    prompt = build_reviewer_system_prompt()
    assert "STANDARD NODE REGISTRY" in prompt
    assert "Operation Correctness & Node Registry Alignment" in prompt
    assert "DETERMINISTIC VALIDATION FACTS" in prompt
    assert "STANDARD NODE REGISTRY" in REVIEWER_SYSTEM_PROMPT


# -------------------------------------------------------------------
# 3. Node Registry API endpoints
# -------------------------------------------------------------------

def test_api_list_categories(client: TestClient, registry: NodeRegistry):
    response = client.get("/api/registry/categories")
    assert response.status_code == 200
    assert response.json() == registry.get_categories()


def test_api_list_nodes_all(client: TestClient, registry: NodeRegistry):
    response = client.get("/api/registry/nodes")
    assert response.status_code == 200
    data = response.json()
    assert data["total_nodes"] == len(registry.list_all())
    assert len(data["nodes"]) == data["total_nodes"]
    assert all(n["executable"] for n in data["nodes"])


def test_api_list_nodes_filtered_by_category(client: TestClient):
    response = client.get("/api/registry/nodes?category=logic")
    assert response.status_code == 200
    data = response.json()
    assert data["total_nodes"] >= 2
    for node in data["nodes"]:
        assert node["category"] == "logic"


def test_api_get_specific_node(client: TestClient):
    response = client.get("/api/registry/nodes/core.if")
    assert response.status_code == 200
    node = response.json()
    assert node["operation_id"] == "core.if" and node["ports_out"] == ["true", "false"]


def test_api_get_unknown_and_removed_node_404(client: TestClient):
    for node_type in ["quantum_teleportation_node", "llm_agent"]:
        response = client.get(f"/api/registry/nodes/{node_type}")
        assert response.status_code == 404
        assert "not found" in response.json().get("detail", "").lower()


def test_api_legacy_catalogue(client: TestClient):
    response = client.get("/api/registry/legacy")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 24
    agent = next(item for item in data if item["node_type"] == "llm_agent")
    assert "AI Agent" in agent["replacement"] and agent["reason"]
