"""Mock workflow generator for local development and testing when GEMINI_API_KEY is unset.

NOTE: This is strictly a development/testing fallback. Every returned workflow is
clearly marked with '[MOCK DEV MODE]' in its name and description so it is never
confused with real LLM-generated output.
"""

from typing import List
import uuid

from app.schemas.workflow import EdgeSchema, NodeSchema, ToolSchema, WorkflowSchema


def generate_mock_workflow(prompt: str) -> WorkflowSchema:
    """Generate a valid, domain-appropriate mock workflow for local testing."""
    prompt_lower = prompt.lower()
    wf_id = f"mock-{uuid.uuid4().hex[:8]}"

    if "invoice" in prompt_lower or "expense" in prompt_lower or "billing" in prompt_lower:
        return WorkflowSchema(
            workflow_id=wf_id,
            workflow_name="[MOCK DEV MODE] Automated Invoice Processing & Approval",
            description=(
                "[MOCK DEV MODE - No GEMINI_API_KEY configured] Automatically extracts invoice data, "
                "verifies line items against ERP, routes for manager approval if over threshold, "
                "and schedules payment."
            ),
            nodes=[
                NodeSchema(
                    id="node_invoice_trigger",
                    type="trigger",
                    label="Invoice Email Received",
                    description="Monitors accounts-payable inbox for incoming vendor invoices.",
                    config={"mailbox": "ap@company.com", "filter": "has:attachment .pdf"},
                    tool=ToolSchema(name="Gmail", operation="watch_inbox", status="not_connected"),
                ),
                NodeSchema(
                    id="node_extract_data",
                    type="document_extraction",
                    label="Extract Invoice Data",
                    description="Extracts vendor details, amount, PO number, and line items from PDF.",
                    config={"extraction_format": "json", "confidence_threshold": 0.95},
                    tool=ToolSchema(name="DocumentAI", operation="parse_invoice", status="not_connected"),
                ),
                NodeSchema(
                    id="node_validate_po",
                    type="database_lookup",
                    label="Verify PO in ERP",
                    description="Validates PO number and matching line items in the ERP system.",
                    config={"erp_table": "purchase_orders", "match_tolerance": 0.01},
                    tool=ToolSchema(name="PostgreSQL", operation="query_po", status="not_connected"),
                ),
                NodeSchema(
                    id="node_threshold_check",
                    type="condition",
                    label="Amount > $5,000?",
                    description="Checks if total invoice amount exceeds auto-approval threshold.",
                    config={"threshold": 5000, "currency": "USD"},
                ),
                NodeSchema(
                    id="node_manual_approval",
                    type="approval",
                    label="Request Manager Approval",
                    description="Sends approval request to finance manager with invoice summary.",
                    config={"channel": "#finance-approvals", "timeout_hours": 24},
                    tool=ToolSchema(name="Slack", operation="send_approval_card", status="not_connected"),
                ),
                NodeSchema(
                    id="node_schedule_payment",
                    type="payment_execution",
                    label="Schedule Payment",
                    description="Submits approved invoice to payment gateway for scheduled batch payout.",
                    config={"payment_method": "ACH", "terms": "Net-30"},
                    tool=ToolSchema(name="Stripe", operation="create_payout", status="not_connected"),
                ),
                NodeSchema(
                    id="node_notify_vendor",
                    type="notification",
                    label="Notify Vendor",
                    description="Sends confirmation email to vendor with payment schedule.",
                    config={"template": "payment_scheduled_v2"},
                    tool=ToolSchema(name="SendGrid", operation="send_email", status="not_connected"),
                ),
            ],
            edges=[
                EdgeSchema(id="e1", source="node_invoice_trigger", target="node_extract_data"),
                EdgeSchema(id="e2", source="node_extract_data", target="node_validate_po"),
                EdgeSchema(id="e3", source="node_validate_po", target="node_threshold_check"),
                EdgeSchema(
                    id="e4_high",
                    source="node_threshold_check",
                    target="node_manual_approval",
                    label="Yes (> $5k)",
                    condition="amount > 5000",
                ),
                EdgeSchema(
                    id="e4_low",
                    source="node_threshold_check",
                    target="node_schedule_payment",
                    label="No (<= $5k Auto)",
                    condition="amount <= 5000",
                ),
                EdgeSchema(id="e5", source="node_manual_approval", target="node_schedule_payment", label="Approved"),
                EdgeSchema(id="e6", source="node_schedule_payment", target="node_notify_vendor"),
            ],
            start_nodes=["node_invoice_trigger"],
            end_nodes=["node_notify_vendor"],
        )

    if "research" in prompt_lower or "search" in prompt_lower or "gather" in prompt_lower:
        return WorkflowSchema(
            workflow_id=wf_id,
            workflow_name="[MOCK DEV MODE] Automated Market & Web Research Pipeline",
            description=(
                "[MOCK DEV MODE - No GEMINI_API_KEY configured] Executes search queries across web sources, "
                "scrapes and synthesizes findings, runs LLM analysis, and publishes a structured research brief."
            ),
            nodes=[
                NodeSchema(
                    id="node_topic_input",
                    type="trigger",
                    label="Research Topic Trigger",
                    description="Receives research query or scheduled research brief topic.",
                    config={"source": "api_trigger"},
                ),
                NodeSchema(
                    id="node_web_search",
                    type="search",
                    label="Search Web & Academic Sources",
                    description="Gathers top 10 relevant articles and news sources for the topic.",
                    config={"max_results": 10, "recency": "past_month"},
                    tool=ToolSchema(name="GoogleSearch", operation="search", status="not_connected"),
                ),
                NodeSchema(
                    id="node_scrape_articles",
                    type="data_extraction",
                    label="Extract Article Text",
                    description="Extracts main text and removes ads and boilerplate from target URLs.",
                    config={"extract_metadata": True},
                    tool=ToolSchema(name="WebScraper", operation="extract_content", status="not_connected"),
                ),
                NodeSchema(
                    id="node_llm_synthesize",
                    type="llm_agent",
                    label="Synthesize Insights (LLM)",
                    description="Analyzes key trends, quotes, pros/cons, and executive takeaways.",
                    config={"model": "gemini-2.5-flash", "temperature": 0.2},
                ),
                NodeSchema(
                    id="node_format_report",
                    type="transform",
                    label="Format Markdown Report",
                    description="Generates executive PDF and Markdown formatted document.",
                    config={"format": "markdown_and_pdf"},
                ),
                NodeSchema(
                    id="node_publish_notion",
                    type="output",
                    label="Publish to Notion & Slack",
                    description="Saves research dossier to knowledge base and alerts team on Slack.",
                    config={"notion_database": "Research Briefs", "slack_channel": "#market-insights"},
                    tool=ToolSchema(name="Notion", operation="create_page", status="not_connected"),
                ),
            ],
            edges=[
                EdgeSchema(id="e1", source="node_topic_input", target="node_web_search"),
                EdgeSchema(id="e2", source="node_web_search", target="node_scrape_articles"),
                EdgeSchema(id="e3", source="node_scrape_articles", target="node_llm_synthesize"),
                EdgeSchema(id="e4", source="node_llm_synthesize", target="node_format_report"),
                EdgeSchema(id="e5", source="node_format_report", target="node_publish_notion"),
            ],
            start_nodes=["node_topic_input"],
            end_nodes=["node_publish_notion"],
        )

    if "slack" in prompt_lower or "notification" in prompt_lower or "alert" in prompt_lower:
        return WorkflowSchema(
            workflow_id=wf_id,
            workflow_name="[MOCK DEV MODE] Email Triage with Slack Escalation",
            description=(
                "[MOCK DEV MODE - No GEMINI_API_KEY configured] Triages inbound emails, "
                "classifies priority with LLM, alerts team on Slack for urgent issues, "
                "and creates a tracker ticket."
            ),
            nodes=[
                NodeSchema(
                    id="node_email_ingress",
                    type="trigger",
                    label="Inbound Email",
                    description="Ingests incoming customer or team email messages.",
                    config={"inbox": "support@company.com"},
                    tool=ToolSchema(name="Gmail", operation="receive_message", status="not_connected"),
                ),
                NodeSchema(
                    id="node_classify_priority",
                    type="llm_agent",
                    label="Classify Priority (LLM)",
                    description="Evaluates sentiment, urgency, and customer SLA tier.",
                    config={"categories": ["P0-Urgent", "P1-High", "P2-Standard"]},
                ),
                NodeSchema(
                    id="node_priority_branch",
                    type="condition",
                    label="Is Urgent (P0/P1)?",
                    description="Routes high-urgency issues to real-time alerting.",
                    config={"condition_field": "priority"},
                ),
                NodeSchema(
                    id="node_slack_alert",
                    type="notification",
                    label="Send Slack Escalation",
                    description="Posts urgent alert with mention in on-call channel.",
                    config={"channel": "#support-oncall", "mention": "@oncall"},
                    tool=ToolSchema(name="Slack", operation="post_message", status="not_connected"),
                ),
                NodeSchema(
                    id="node_create_jira",
                    type="ticketing",
                    label="Create Jira Ticket",
                    description="Creates issue in engineering or support queue.",
                    config={"project": "SUP", "issue_type": "Task"},
                    tool=ToolSchema(name="Jira", operation="create_issue", status="not_connected"),
                ),
                NodeSchema(
                    id="node_auto_ack",
                    type="notification",
                    label="Send Auto-Acknowledgement",
                    description="Sends acknowledgement email with ticket link to customer.",
                    config={"template": "ticket_created_ack"},
                    tool=ToolSchema(name="Gmail", operation="send_reply", status="not_connected"),
                ),
            ],
            edges=[
                EdgeSchema(id="e1", source="node_email_ingress", target="node_classify_priority"),
                EdgeSchema(id="e2", source="node_classify_priority", target="node_priority_branch"),
                EdgeSchema(
                    id="e3_urgent",
                    source="node_priority_branch",
                    target="node_slack_alert",
                    label="Yes (Urgent)",
                    condition="priority in ['P0', 'P1']",
                ),
                EdgeSchema(
                    id="e3_normal",
                    source="node_priority_branch",
                    target="node_create_jira",
                    label="No (Standard)",
                    condition="priority == 'P2'",
                ),
                EdgeSchema(id="e4", source="node_slack_alert", target="node_create_jira"),
                EdgeSchema(id="e5", source="node_create_jira", target="node_auto_ack"),
            ],
            start_nodes=["node_email_ingress"],
            end_nodes=["node_auto_ack"],
        )

    # Default fallback: Customer Support & Order Verification workflow (the prompt's canonical example)
    return WorkflowSchema(
        workflow_id=wf_id,
        workflow_name="[MOCK DEV MODE] Customer Support Email & Order Verification Flow",
        description=(
            "[MOCK DEV MODE - No GEMINI_API_KEY configured] Receives customer emails, identifies the issue, "
            "checks order status from database, generates an AI response, and emails customer."
        ),
        nodes=[
            NodeSchema(
                id="node_receive_email",
                type="trigger",
                label="Receive Customer Email",
                description="Listens for inbound support emails on support@company.com.",
                config={"inbox": "support@company.com", "polling_interval_sec": 30},
                tool=ToolSchema(name="Gmail", operation="receive", status="not_connected"),
            ),
            NodeSchema(
                id="node_classify_issue",
                type="llm_agent",
                label="Identify Issue & Intent",
                description="Uses LLM to categorize inquiry (order inquiry, return, complaint) and extract order ID.",
                config={"model": "gemini-2.5-flash", "extract_entities": ["order_id", "issue_type"]},
            ),
            NodeSchema(
                id="node_check_order_db",
                type="database_query",
                label="Query Order Database",
                description="Looks up customer order status, tracking number, and delivery date.",
                config={"table": "orders", "key": "order_id"},
                tool=ToolSchema(name="PostgreSQL", operation="lookup_order", status="not_connected"),
            ),
            NodeSchema(
                id="node_evaluate_status",
                type="condition",
                label="Order Found?",
                description="Checks if order record exists and retrieves delivery state.",
                config={"condition": "order != null"},
            ),
            NodeSchema(
                id="node_generate_response",
                type="llm_agent",
                label="Generate Response with LLM",
                description="Drafts a personalized, empathetic response incorporating live order status.",
                config={"model": "gemini-2.5-flash", "tone": "helpful_and_professional"},
            ),
            NodeSchema(
                id="node_escalate_human",
                type="notification",
                label="Escalate to Human Agent",
                description="Routes ticket to human support rep if order cannot be resolved automatically.",
                config={"queue": "tier_2_support"},
                tool=ToolSchema(name="Zendesk", operation="create_ticket", status="not_connected"),
            ),
            NodeSchema(
                id="node_send_email",
                type="output",
                label="Send Response to Customer",
                description="Dispatches the generated response email to customer address.",
                config={"from_address": "support@company.com"},
                tool=ToolSchema(name="Gmail", operation="send_email", status="not_connected"),
            ),
        ],
        edges=[
            EdgeSchema(id="edge_1", source="node_receive_email", target="node_classify_issue"),
            EdgeSchema(id="edge_2", source="node_classify_issue", target="node_check_order_db"),
            EdgeSchema(id="edge_3", source="node_check_order_db", target="node_evaluate_status"),
            EdgeSchema(
                id="edge_4_found",
                source="node_evaluate_status",
                target="node_generate_response",
                label="Order Found",
                condition="order.status != null",
            ),
            EdgeSchema(
                id="edge_4_not_found",
                source="node_evaluate_status",
                target="node_escalate_human",
                label="Order Missing",
                condition="order.status == null",
            ),
            EdgeSchema(id="edge_5", source="node_generate_response", target="node_send_email"),
            EdgeSchema(id="edge_6", source="node_escalate_human", target="node_send_email", label="Escalation Ack"),
        ],
        start_nodes=["node_receive_email"],
        end_nodes=["node_send_email"],
    )
