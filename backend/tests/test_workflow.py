"""Comprehensive tests for AI Workflow Designer backend and Semantic Reviewer.

Covers:
- GET /health
- GraphValidator topologies (sequential, conditional branching, broken edges, orphan nodes, dead ends)
- 5 diverse workflow requirements (mock generation)
- Semantic Review schemas (passed, failed, needs_clarification)
- 7 Reviewer audit scenarios (complete, missing operation, missing condition, incorrect tool, incorrect connection, ambiguous requirement, correction loop)
- Model separation check (Generator: gemini-3.8-flash/gemini-3.5-flash-lite vs Reviewer: gemma-4-31b-it)
- POST /api/workflows/generate endpoint
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.review import (
    RequirementCoverage,
    RequirementStatus,
    ReviewIssue,
    ReviewStatus,
    WorkflowReview,
)
from app.schemas.workflow import EdgeSchema, NodeSchema, ToolSchema, WorkflowSchema
from app.services.llm_service import LLMService
from app.services.mock_workflow_generator import generate_mock_workflow
from app.services.workflow_generator import WorkflowGenerator
from app.services.workflow_reviewer import REVIEWER_SYSTEM_PROMPT, WorkflowReviewer
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
# 3. 5 Diverse Requirements Tests (Mock Generation)
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
    wf = generate_mock_workflow(prompt)
    assert isinstance(wf, WorkflowSchema)
    assert wf.workflow_id
    assert wf.workflow_name
    assert len(wf.nodes) >= 3
    assert len(wf.edges) >= 2
    assert len(wf.start_nodes) >= 1
    assert len(wf.end_nodes) >= 1

    graph_res = GraphValidator.validate(wf)
    assert graph_res.is_valid is True, f"Graph validation failed for {category}: {graph_res.errors}"


# ---------------------------------------------------------------------------
# 4. Review Schema Validation Tests
# ---------------------------------------------------------------------------
def test_review_schema_passed():
    review = WorkflowReview(
        status=ReviewStatus.PASSED,
        summary="All requirements covered.",
        requirement_coverage=[
            RequirementCoverage(requirement_id="R1", status=RequirementStatus.COVERED, evidence=["node_1"])
        ],
        issues=[],
    )
    assert review.status == ReviewStatus.PASSED
    assert len(review.requirement_coverage) == 1
    assert review.clarification_required is False


def test_review_schema_failed():
    review = WorkflowReview(
        status=ReviewStatus.FAILED,
        summary="Missing database update.",
        requirement_coverage=[
            RequirementCoverage(
                requirement_id="R1",
                description="Database update",
                status=RequirementStatus.MISSING,
                evidence=[],
                explanation="No database node exists.",
            )
        ],
        issues=[
            ReviewIssue(
                issue_type="missing_operation",
                severity="high",
                requirement_id="R1",
                description="Database update operation is missing.",
                suggested_correction="Add database update node to success branch.",
            )
        ],
    )
    assert review.status == ReviewStatus.FAILED
    assert len(review.issues) == 1
    assert review.issues[0].severity == "high"


def test_review_schema_needs_clarification():
    review = WorkflowReview(
        status=ReviewStatus.NEEDS_CLARIFICATION,
        summary="Requirement is ambiguous: no action specified for rejected orders.",
        requirement_coverage=[
            RequirementCoverage(
                requirement_id="R1",
                description="Handle rejected order",
                status=RequirementStatus.UNCLEAR,
                evidence=[],
                explanation="Prompt does not specify whether to cancel, retry, or alert.",
            )
        ],
        issues=[],
        clarification_required=True,
    )
    assert review.status == ReviewStatus.NEEDS_CLARIFICATION
    assert review.clarification_required is True


# ---------------------------------------------------------------------------
# 5. 7 Reviewer Scenario Tests (per Master Prompt Section 12)
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_workflow() -> WorkflowSchema:
    return WorkflowSchema(
        workflow_id="order-process",
        workflow_name="Order Processing",
        description="Process orders, check payment, invoice, notify",
        nodes=[
            NodeSchema(id="n_recv", type="trigger", label="Order Received", config={}),
            NodeSchema(id="n_check", type="condition", label="Check Payment", config={}),
            NodeSchema(id="n_inv", type="action", label="Generate Invoice", config={}),
            NodeSchema(id="n_email", type="notification", label="Email Customer", config={}),
            NodeSchema(id="n_admin", type="notification", label="Alert Admin", config={}),
        ],
        edges=[
            EdgeSchema(id="e1", source="n_recv", target="n_check"),
            EdgeSchema(id="e2", source="n_check", target="n_inv", label="success"),
            EdgeSchema(id="e3", source="n_inv", target="n_email"),
            EdgeSchema(id="e4", source="n_check", target="n_admin", label="failure"),
        ],
        start_nodes=["n_recv"],
        end_nodes=["n_email", "n_admin"],
    )


def test_scenario_1_complete_workflow(sample_workflow: WorkflowSchema):
    """Case 1: Complete workflow where all requirements are represented."""
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_review_json.return_value = json.dumps({
        "status": "passed",
        "summary": "All operations and branches are correctly represented.",
        "requirement_coverage": [
            {"requirement_id": "R1", "description": "Order trigger", "status": "covered", "evidence": ["n_recv"]},
            {"requirement_id": "R2", "description": "Payment check", "status": "covered", "evidence": ["n_check"]},
            {"requirement_id": "R3", "description": "Invoice & email", "status": "covered", "evidence": ["n_inv", "n_email"]},
            {"requirement_id": "R4", "description": "Admin alert", "status": "covered", "evidence": ["n_admin"]},
        ],
        "issues": [],
        "clarification_required": False,
    })

    reviewer = WorkflowReviewer(llm_service=mock_llm)
    review = reviewer.review("Process order and check payment...", sample_workflow)

    assert review.status == ReviewStatus.PASSED
    assert len(review.issues) == 0
    assert len(review.requirement_coverage) == 4
    mock_llm.generate_review_json.assert_called_once()


def test_scenario_2_missing_operation(sample_workflow: WorkflowSchema):
    """Case 2: Missing operation (e.g. database update was requested but omitted)."""
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_review_json.return_value = json.dumps({
        "status": "failed",
        "summary": "The requested database update operation is omitted.",
        "requirement_coverage": [
            {"requirement_id": "R1", "description": "Database update", "status": "missing", "evidence": [], "explanation": "No database update node."},
        ],
        "issues": [
            {
                "issue_type": "missing_operation",
                "severity": "high",
                "requirement_id": "R1",
                "description": "Database update was requested upon payment success but is absent.",
                "suggested_correction": "Add a database update node after payment succeeds.",
            }
        ],
        "clarification_required": False,
    })

    reviewer = WorkflowReviewer(llm_service=mock_llm)
    review = reviewer.review("Update database after payment...", sample_workflow)

    assert review.status == ReviewStatus.FAILED
    assert len(review.issues) == 1
    assert review.issues[0].issue_type == "missing_operation"
    assert review.issues[0].severity == "high"


def test_scenario_3_missing_condition():
    """Case 3: Missing condition branch (payment success/failure branches not represented)."""
    no_branch_wf = WorkflowSchema(
        workflow_id="no-branch",
        workflow_name="Linear Order",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Order Received", config={}),
            NodeSchema(id="n2", type="action", label="Send Email", config={}),
        ],
        edges=[EdgeSchema(id="e1", source="n1", target="n2")],
        start_nodes=["n1"],
        end_nodes=["n2"],
    )

    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_review_json.return_value = json.dumps({
        "status": "failed",
        "summary": "Conditional branching for payment status is completely missing.",
        "requirement_coverage": [
            {"requirement_id": "R1", "description": "Check payment success/failure", "status": "missing", "evidence": []},
        ],
        "issues": [
            {
                "issue_type": "missing_condition",
                "severity": "high",
                "requirement_id": "R1",
                "description": "Workflow is linear and ignores payment success vs failure branches.",
                "suggested_correction": "Introduce a condition node with true/false branches.",
            }
        ],
    })

    reviewer = WorkflowReviewer(llm_service=mock_llm)
    review = reviewer.review("Check payment; if ok invoice else alert admin", no_branch_wf)

    assert review.status == ReviewStatus.FAILED
    assert any(i.issue_type == "missing_condition" for i in review.issues)


def test_scenario_4_incorrect_operation():
    """Case 4: Incorrect operation / tool selected (unrelated tool chosen)."""
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_review_json.return_value = json.dumps({
        "status": "failed",
        "summary": "Unrelated tool selected for database operation.",
        "issues": [
            {
                "issue_type": "incorrect_tool",
                "severity": "medium",
                "description": "Selected Twitter tool for internal SQL database query.",
                "suggested_correction": "Use PostgreSQL or Database tool instead of Twitter.",
            }
        ],
    })

    reviewer = WorkflowReviewer(llm_service=mock_llm)
    review = reviewer.review("Query customer DB", WorkflowSchema(
        workflow_id="wf", workflow_name="WF",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Start", config={}),
            NodeSchema(id="n2", type="action", label="Tweet", config={}, tool=ToolSchema(name="Twitter", operation="post")),
        ],
        edges=[EdgeSchema(id="e1", source="n1", target="n2")],
        start_nodes=["n1"], end_nodes=["n2"],
    ))

    assert review.status == ReviewStatus.FAILED
    assert review.issues[0].issue_type == "incorrect_tool"


def test_scenario_5_incorrect_connection():
    """Case 5: Incorrect connection (failure branch leads to success operation)."""
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_review_json.return_value = json.dumps({
        "status": "failed",
        "summary": "Failure branch incorrectly routes to payout operation.",
        "issues": [
            {
                "issue_type": "incorrect_connection",
                "severity": "high",
                "affected_edge_ids": ["e_fail"],
                "description": "The 'payment_failed' edge points to 'PayoutVendor' node.",
                "suggested_correction": "Route payment_failed to 'NotifyAdmin' instead.",
            }
        ],
    })

    reviewer = WorkflowReviewer(llm_service=mock_llm)
    review = reviewer.review("If payment fails notify admin, if succeeds payout", WorkflowSchema(
        workflow_id="wf", workflow_name="WF",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Start", config={}),
            NodeSchema(id="n2", type="action", label="PayoutVendor", config={}),
        ],
        edges=[EdgeSchema(id="e_fail", source="n1", target="n2", label="failed")],
        start_nodes=["n1"], end_nodes=["n2"],
    ))

    assert review.status == ReviewStatus.FAILED
    assert review.issues[0].issue_type == "incorrect_connection"


def test_scenario_6_ambiguous_requirement():
    """Case 6: Ambiguous requirement requiring clarification."""
    mock_llm = MagicMock(spec=LLMService)
    mock_llm.generate_review_json.return_value = json.dumps({
        "status": "needs_clarification",
        "summary": "User did not specify what occurs when risk score is moderate (between 30 and 70).",
        "requirement_coverage": [
            {"requirement_id": "R1", "description": "Moderate risk handling", "status": "unclear", "explanation": "Threshold action undefined."},
        ],
        "issues": [],
        "clarification_required": True,
    })

    reviewer = WorkflowReviewer(llm_service=mock_llm)
    review = reviewer.review("Check risk score: if high block, if low approve", WorkflowSchema(
        workflow_id="wf", workflow_name="WF",
        nodes=[
            NodeSchema(id="n1", type="trigger", label="Start", config={}),
            NodeSchema(id="n2", type="output", label="End", config={}),
        ],
        edges=[EdgeSchema(id="e1", source="n1", target="n2")],
        start_nodes=["n1"], end_nodes=["n2"],
    ))

    assert review.status == ReviewStatus.NEEDS_CLARIFICATION
    assert review.clarification_required is True


def test_scenario_7_corrected_workflow():
    """Case 7: Initial review fails, correction succeeds and re-review passes."""
    mock_llm = MagicMock(spec=LLMService)

    # Initial generation JSON
    initial_wf_json = json.dumps({
        "workflow_id": "wf-v1",
        "workflow_name": "WF V1",
        "description": "V1",
        "nodes": [
            {"id": "n1", "type": "trigger", "label": "Start", "config": {}},
            {"id": "n2", "type": "output", "label": "End", "config": {}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        "start_nodes": ["n1"],
        "end_nodes": ["n2"],
    })
    mock_llm.generate_workflow_json.return_value = initial_wf_json

    # Corrected generation JSON
    corrected_wf_json = json.dumps({
        "workflow_id": "wf-v2",
        "workflow_name": "WF V2 Corrected",
        "description": "V2 Corrected",
        "nodes": [
            {"id": "n1", "type": "trigger", "label": "Start", "config": {}},
            {"id": "n_db", "type": "database_update", "label": "Save to DB", "config": {}},
            {"id": "n2", "type": "output", "label": "End", "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n_db"},
            {"id": "e2", "source": "n_db", "target": "n2"},
        ],
        "start_nodes": ["n1"],
        "end_nodes": ["n2"],
    })
    mock_llm.fix_workflow_json.return_value = corrected_wf_json

    # Review sequence: first call fails (missing DB), second call passes!
    review_1 = json.dumps({
        "status": "failed",
        "summary": "Missing DB update.",
        "issues": [{"issue_type": "missing_operation", "severity": "high", "description": "DB missing", "suggested_correction": "Add DB node"}],
        "clarification_required": False,
    })
    review_2 = json.dumps({
        "status": "passed",
        "summary": "All operations present including DB update.",
        "issues": [],
        "clarification_required": False,
    })
    mock_llm.generate_review_json.side_effect = [review_1, review_2]

    # Test settings
    settings = MagicMock()
    settings.has_gemini_api_key = True
    settings.MOCK_DEV_MODE = False
    settings.MAX_GENERATION_RETRIES = 2
    settings.MAX_REVIEW_CORRECTION_ATTEMPTS = 2
    settings.ENABLE_WORKFLOW_REVIEW = True

    generator = WorkflowGenerator(llm_service=mock_llm, settings=settings)
    result = generator.generate("Save to database and finish", enable_review=True)

    assert result["review_status"] == "passed"
    assert result["correction_attempts"] == 1
    assert any(n["id"] == "n_db" for n in result["nodes"])
    assert mock_llm.fix_workflow_json.called


# ---------------------------------------------------------------------------
# 6. Model Separation Check
# ---------------------------------------------------------------------------
def test_model_separation_configuration():
    """Verify generator and reviewer use distinct models and dedicated prompts."""
    from app.core.config import Settings

    settings = Settings()
    # Generator model is gemini-3.8-flash, fallback is gemini-3.5-flash-lite
    assert settings.GEMINI_MODEL == "gemini-3.8-flash"
    assert settings.GEMINI_FALLBACK_MODEL == "gemini-3.5-flash-lite"
    # Reviewer model is gemma-4-31b-it
    assert settings.GEMINI_REVIEWER_MODEL == "gemma-4-31b-it"

    # Verify REVIEWER_SYSTEM_PROMPT is an independent auditor prompt
    assert "senior workflow architect and semantic auditor" in REVIEWER_SYSTEM_PROMPT
    assert "Evidence-Based Review" in REVIEWER_SYSTEM_PROMPT
    assert "Conditional Logic" in REVIEWER_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 7. API Endpoint Integration Test
# ---------------------------------------------------------------------------
def test_generate_endpoint_validation_error(client: TestClient) -> None:
    # Prompt is too short (< 3 chars)
    payload = {"prompt": "ab"}
    response = client.post("/api/workflows/generate", json=payload)
    assert response.status_code == 422
