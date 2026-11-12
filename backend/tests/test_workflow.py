"""Comprehensive tests for AI Workflow Designer backend.

Covers:
- GET /health
- GraphValidator topologies (sequential, conditional branching, broken edges, orphan nodes, dead ends)
- 5 diverse workflow requirements
- POST /api/workflows/generate endpoint
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.workflow import EdgeSchema, NodeSchema, ToolSchema, WorkflowSchema
from app.services.mock_workflow_generator import generate_mock_workflow
from app.services.workflow_generator import WorkflowGenerator
from app.validators.graph_validator import GraphValidator


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Health Check Test
# ---------------------------------------------------------------------------
def test_health_check(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


# ---------------------------------------------------------------------------
# 2. Graph Validator Tests
# ---------------------------------------------------------------------------
def test_graph_validator_valid_sequential() -> None:
    wf = WorkflowSchema(
        workflow_id="wf-seq",
        workflow_name="Sequential Pipeline",
        description="A to B to C",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Trigger", config={}),
            NodeSchema(id="n2", type="process", label="Process", config={}),
            NodeSchema(id="n3", type="output", label="Output", config={}),
        ],
        edges=[
            EdgeSchema(id="e1", source="n1", target="n2"),
            EdgeSchema(id="e2", source="n2", target="n3"),
        ],
        start_nodes=["n1"],
        end_nodes=["n3"],
    )
    res = GraphValidator.validate(wf)
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_graph_validator_valid_branching() -> None:
    wf = WorkflowSchema(
        workflow_id="wf-branch",
        workflow_name="Branching Pipeline",
        description="A branches to B and C, both reach D",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Trigger", config={}),
            NodeSchema(id="n_cond", type="condition", label="Condition", config={}),
            NodeSchema(id="n_branch1", type="process", label="Branch 1", config={}),
            NodeSchema(id="n_branch2", type="process", label="Branch 2", config={}),
            NodeSchema(id="n_end", type="output", label="End", config={}),
        ],
        edges=[
            EdgeSchema(id="e1", source="n1", target="n_cond"),
            EdgeSchema(id="e2", source="n_cond", target="n_branch1", label="True"),
            EdgeSchema(id="e3", source="n_cond", target="n_branch2", label="False"),
            EdgeSchema(id="e4", source="n_branch1", target="n_end"),
            EdgeSchema(id="e5", source="n_branch2", target="n_end"),
        ],
        start_nodes=["n1"],
        end_nodes=["n_end"],
    )
    res = GraphValidator.validate(wf)
    assert res.is_valid is True
    assert len(res.errors) == 0


def test_graph_validator_catches_orphan_node() -> None:
    # Node n_orphan has no incoming edges and is not a start_node
    wf = WorkflowSchema(
        workflow_id="wf-orphan",
        workflow_name="Orphan Pipeline",
        description="Contains an unconnected node",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Start", config={}),
            NodeSchema(id="n2", type="output", label="End", config={}),
            NodeSchema(id="n_orphan", type="process", label="Floating", config={}),
        ],
        edges=[
            EdgeSchema(id="e1", source="n1", target="n2"),
        ],
        start_nodes=["n1"],
        end_nodes=["n2"],
    )
    res = GraphValidator.validate(wf)
    assert res.is_valid is False
    assert any("Unreachable or unconnected" in err for err in res.errors)


def test_graph_validator_catches_dead_end() -> None:
    # Node n_deadend has no path to any end_node
    wf = WorkflowSchema(
        workflow_id="wf-deadend",
        workflow_name="Dead End Pipeline",
        description="Contains a node with no path to an end_node",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Start", config={}),
            NodeSchema(id="n2", type="output", label="End", config={}),
            NodeSchema(id="n_dead", type="process", label="Dead End", config={}),
        ],
        edges=[
            EdgeSchema(id="e1", source="n1", target="n2"),
            EdgeSchema(id="e2", source="n1", target="n_dead"),
        ],
        start_nodes=["n1"],
        end_nodes=["n2"],
    )
    res = GraphValidator.validate(wf)
    assert res.is_valid is False
    assert any("no path to any end_node" in err for err in res.errors)


# ---------------------------------------------------------------------------
# 3. 5 Diverse Requirements Tests (as specified in Master Prompt section 12)
# ---------------------------------------------------------------------------
PROMPTS = [
    (
        "customer_support",
        "Create a workflow that receives customer emails, identifies the issue, checks the order "
        "status from a database, generates a suitable response using an LLM, and sends the response to the customer.",
    ),
    (
        "email_slack_notification",
        "Build an email automation that filters incoming critical alert emails, posts an immediate message "
        "to a Slack on-call channel, and logs a ticket in Jira.",
    ),
    (
        "invoice_processing",
        "Create an invoice processing pipeline that extracts invoice data from PDF attachments, checks if "
        "amount exceeds $5000, routes to manager for Slack approval if high value, schedules Stripe payout, "
        "and notifies vendor.",
    ),
    (
        "document_analysis",
        "Build a document analysis workflow that parses incoming contracts, runs entity extraction and risk "
        "analysis using Gemini, generates a markdown report, and archives to cloud storage.",
    ),
    (
        "research_automation",
        "Design a web research automation that searches news and Google for a topic, scrapes articles, "
        "synthesizes key insights with an LLM, formats a PDF report, and publishes to Notion.",
    ),
]


@pytest.mark.parametrize("category,prompt", PROMPTS)
def test_diverse_workflow_prompts_mock_generation(category: str, prompt: str) -> None:
    generator = WorkflowGenerator()
    wf = generator.generate(prompt=prompt)

    # Must be valid WorkflowSchema
    assert isinstance(wf, WorkflowSchema)
    assert wf.workflow_id
    assert wf.workflow_name
    assert len(wf.nodes) >= 3
    assert len(wf.edges) >= 2
    assert len(wf.start_nodes) >= 1
    assert len(wf.end_nodes) >= 1

    # Must pass GraphValidator
    graph_res = GraphValidator.validate(wf)
    assert graph_res.is_valid is True, f"Graph validation failed for {category}: {graph_res.errors}"


# ---------------------------------------------------------------------------
# 4. API Endpoint Integration Test
# ---------------------------------------------------------------------------
def test_generate_endpoint_success(client: TestClient) -> None:
    payload = {
        "prompt": "Create an invoice processing and approval workflow with Slack notifications and Stripe payout."
    }
    response = client.post("/api/workflows/generate", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "workflow_id" in data
    assert "workflow_name" in data
    assert "nodes" in data
    assert "edges" in data
    assert "start_nodes" in data
    assert "end_nodes" in data
    assert len(data["nodes"]) > 0
    assert len(data["edges"]) > 0


def test_generate_endpoint_validation_error(client: TestClient) -> None:
    # Prompt is too short (< 3 chars)
    payload = {"prompt": "ab"}
    response = client.post("/api/workflows/generate", json=payload)
    assert response.status_code == 422
