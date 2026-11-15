"""Mock workflow generator for local development and testing when GEMINI_API_KEY is unset.

NOTE: This is strictly a development/testing fallback. Every returned workflow is
clearly marked with '[MOCK DEV MODE]' in its name and description so it is never
confused with real LLM-generated output.

Every mock workflow uses ONLY executable registry operations (Milestone 2 removed
design-only node types). External services without a built-in integration
(email, Slack, payment providers...) are reached through ``http.request`` against
placeholder ``*.example.com`` endpoints, which the user must replace; the
description says so explicitly.
"""

import re
import uuid
from typing import Any, Dict, List, Optional

from app.schemas.workflow import EdgeSchema, NodeSchema, WorkflowSchema

_MOCK = "[MOCK DEV MODE]"
_MOCK_NOTE = (
    "[MOCK DEV MODE - No GEMINI_API_KEY configured] Template workflow built only from executable operations. "
    "External services are called through HTTP Request placeholders (*.example.com) that you must replace "
    "with real endpoints and credentials."
)


def _node(id_: str, type_: str, operation: str, label: str, description: str,
          config: Dict[str, Any]) -> NodeSchema:
    return NodeSchema(id=id_, type=type_, operation=operation, label=label, description=description, config=config)


def _edge(id_: str, source: str, target: str, port: str = "main") -> EdgeSchema:
    return EdgeSchema(id=id_, source=source, target=target, source_port=port,
                      label=port if port in {"true", "false"} else None)


def _rule(left: str, operator: str, right: Any = None) -> Dict[str, Any]:
    rule: Dict[str, Any] = {"left": left, "operator": operator}
    if right is not None:
        rule["right"] = right
    return rule


def _if(id_: str, label: str, rules: List[Dict[str, Any]], combinator: str = "all") -> NodeSchema:
    return _node(id_, "condition", "core.if", label, "Routes to the true or false branch.",
                 {"conditions": {"combinator": combinator, "rules": rules}})


def _http(id_: str, label: str, url: str, body: Optional[Dict[str, Any]] = None, method: str = "POST") -> NodeSchema:
    config: Dict[str, Any] = {"method": method, "url": url, "timeout_seconds": 15}
    if body is not None:
        config.update({"body_type": "json", "body": body})
    return _node(id_, "api_call", "http.request", label, f"{method} {url} (placeholder endpoint).", config)


def _end(id_: str, label: str, output: Any) -> NodeSchema:
    return _node(id_, "end", "core.end", label, "Returns the final output.", {"output": output})


def _set(id_: str, label: str, fields: List[Dict[str, Any]]) -> NodeSchema:
    return _node(id_, "set_variable", "core.set", label, "Prepares named fields.",
                 {"fields": fields, "keep_input": False})


def _webhook() -> NodeSchema:
    return _node("webhook_trigger_1", "webhook_trigger", "core.webhook_trigger", "Incoming Request",
                 "Starts the workflow when a JSON payload is POSTed to the webhook URL.", {"method": "POST"})


def _workflow(wf_id: str, name: str, summary: str, nodes: List[NodeSchema], edges: List[EdgeSchema]) -> WorkflowSchema:
    return WorkflowSchema(workflow_id=wf_id, workflow_name=f"{_MOCK} {name}", description=f"{_MOCK_NOTE} {summary}",
                          nodes=nodes, edges=edges)


def generate_mock_workflow(prompt: str) -> WorkflowSchema:
    """Generate a domain-appropriate, executable mock workflow for local testing."""
    prompt_lower = prompt.lower()
    wf_id = f"mock-{uuid.uuid4().hex[:8]}"

    if re.search(r"\b(http|fetch|endpoint|url|api request)\b", prompt_lower):
        return _executable_http_workflow(wf_id)
    if any(k in prompt_lower for k in ("invoice", "expense", "billing", "payment")):
        return _invoice_workflow(wf_id)
    if any(k in prompt_lower for k in ("support", "customer", "ticket", "order")):
        return _support_workflow(wf_id)
    if any(k in prompt_lower for k in ("email", "slack", "alert", "notification", "notify")):
        return _alert_workflow(wf_id)
    return _generic_workflow(wf_id, prompt)


def _invoice_workflow(wf_id: str) -> WorkflowSchema:
    return _workflow(
        wf_id, "Invoice Approval Routing",
        "Receives an invoice as JSON, requests approval for amounts above 5000 and otherwise schedules payment.",
        [
            _webhook(),
            _set("set_1", "Normalize Invoice", [
                {"name": "vendor", "value": "{{trigger.body.vendor}}", "type": "string"},
                {"name": "amount", "value": "{{trigger.body.amount}}", "type": "number"},
                {"name": "invoice_id", "value": "{{trigger.body.invoice_id}}", "type": "string"},
            ]),
            _if("if_1", "Amount > 5000?", [_rule("{{nodes.set_1.output.amount}}", "gt", 5000)]),
            _http("http_1", "Request Manager Approval", "https://approvals.example.com/requests",
                  {"invoice_id": "{{nodes.set_1.output.invoice_id}}", "amount": "{{nodes.set_1.output.amount}}"}),
            _http("http_2", "Schedule Payment", "https://payments.example.com/payouts",
                  {"vendor": "{{nodes.set_1.output.vendor}}", "amount": "{{nodes.set_1.output.amount}}"}),
            _end("end_1", "Approval Requested", {"route": "approval", "status": "{{nodes.http_1.output.status_code}}"}),
            _end("end_2", "Payment Scheduled", {"route": "payment", "status": "{{nodes.http_2.output.status_code}}"}),
        ],
        [_edge("e1", "webhook_trigger_1", "set_1"), _edge("e2", "set_1", "if_1"),
         _edge("e3", "if_1", "http_1", "true"), _edge("e4", "http_1", "end_1"),
         _edge("e5", "if_1", "http_2", "false"), _edge("e6", "http_2", "end_2")],
    )


def _support_workflow(wf_id: str) -> WorkflowSchema:
    return _workflow(
        wf_id, "Customer Support Triage",
        "Receives a support message, escalates urgent ones and acknowledges the rest.",
        [
            _webhook(),
            _set("set_1", "Extract Message", [
                {"name": "email", "value": "{{trigger.body.email}}", "type": "string"},
                {"name": "message", "value": "{{trigger.body.message}}", "type": "string"},
            ]),
            _if("if_1", "Urgent?", [_rule("{{nodes.set_1.output.message}}", "contains", "urgent"),
                                    _rule("{{nodes.set_1.output.message}}", "contains", "refund")], "any"),
            _http("http_1", "Escalate to On-Call", "https://helpdesk.example.com/escalations",
                  {"email": "{{nodes.set_1.output.email}}", "message": "{{nodes.set_1.output.message}}"}),
            _http("http_2", "Send Acknowledgement", "https://mail.example.com/send",
                  {"to": "{{nodes.set_1.output.email}}", "template": "ack"}),
            _end("end_1", "Escalated", {"escalated": True}),
            _end("end_2", "Acknowledged", {"escalated": False}),
        ],
        [_edge("e1", "webhook_trigger_1", "set_1"), _edge("e2", "set_1", "if_1"),
         _edge("e3", "if_1", "http_1", "true"), _edge("e4", "http_1", "end_1"),
         _edge("e5", "if_1", "http_2", "false"), _edge("e6", "http_2", "end_2")],
    )


def _alert_workflow(wf_id: str) -> WorkflowSchema:
    return _workflow(
        wf_id, "Critical Alert Notification",
        "Receives alert events, keeps the critical ones and posts them to a chat webhook.",
        [
            _webhook(),
            _node("filter_1", "filter", "core.filter", "Keep Critical Alerts", "Keeps alerts with severity 'critical'.",
                  {"items": "{{trigger.body.alerts}}",
                   "conditions": {"combinator": "all", "rules": [_rule("{{item.severity}}", "eq", "critical")]}}),
            _if("if_1", "Any Critical?", [_rule("{{nodes.filter_1.output.kept}}", "gt", 0)]),
            _http("http_1", "Post to Chat Webhook", "https://chat.example.com/webhook",
                  {"text": "Critical alerts: {{nodes.filter_1.output.kept}}", "alerts": "{{nodes.filter_1.output.items}}"}),
            _end("end_1", "Notified", {"notified": True, "count": "{{nodes.filter_1.output.kept}}"}),
            _end("end_2", "Nothing Critical", {"notified": False}),
        ],
        [_edge("e1", "webhook_trigger_1", "filter_1"), _edge("e2", "filter_1", "if_1"),
         _edge("e3", "if_1", "http_1", "true"), _edge("e4", "http_1", "end_1"),
         _edge("e5", "if_1", "end_2", "false")],
    )


def _generic_workflow(wf_id: str, prompt: str) -> WorkflowSchema:
    return _workflow(
        wf_id, "Data Processing Pipeline",
        f"Generic template for: {prompt[:120]}",
        [
            _node("manual_trigger_1", "manual_trigger", "core.manual_trigger", "Start Manually",
                  "Run payload: {\"items\": [...], \"title\": string}.",
                  {"sample_payload": {"title": "Report", "items": [{"name": "a", "value": 1}]}}),
            _set("set_1", "Prepare Fields", [
                {"name": "title", "value": "{{trigger.title}}", "type": "string"},
                {"name": "items", "value": "{{trigger.items}}", "type": "array"},
            ]),
            _node("transform_1", "data_transform", "core.transform", "Build Result", "Maps the prepared fields.",
                  {"mappings": {"report.title": "{{nodes.set_1.output.title}}",
                                "report.items": "{{nodes.set_1.output.items}}"}}),
            _end("end_1", "Return Result", "{{nodes.transform_1.output.report}}"),
        ],
        [_edge("e1", "manual_trigger_1", "set_1"), _edge("e2", "set_1", "transform_1"),
         _edge("e3", "transform_1", "end_1")],
    )


def _executable_http_workflow(wf_id: str) -> WorkflowSchema:
    """Mock design that uses only executable registry operations (Manual -> Set -> If -> HTTP/End)."""
    return WorkflowSchema(
        workflow_id=wf_id,
        workflow_name="[MOCK DEV MODE] Conditional HTTP Fetch",
        description=(
            "[MOCK DEV MODE - No GEMINI_API_KEY configured] Reads an amount and URL from the run payload, "
            "fetches the URL when the amount exceeds 100, and returns the response."
        ),
        nodes=[
            NodeSchema(id="trigger_1", type="manual_trigger", operation="core.manual_trigger",
                       label="Start Manually", description="Run payload: {\"amount\": number, \"url\": string}.",
                       config={"sample_payload": {"amount": 150, "url": "https://httpbin.org/get"}}),
            NodeSchema(id="set_1", type="set_variable", operation="core.set", label="Prepare Request",
                       description="Copies amount and target URL from the trigger payload.",
                       config={"fields": [
                           {"name": "amount", "value": "{{trigger.amount}}", "type": "number"},
                           {"name": "target_url", "value": "{{trigger.url}}", "type": "string"},
                       ], "keep_input": False}),
            NodeSchema(id="if_1", type="condition", operation="core.if", label="Amount Above 100?",
                       description="Routes to the HTTP call only for large amounts.",
                       config={"conditions": {"combinator": "all", "rules": [
                           {"left": "{{nodes.set_1.output.amount}}", "operator": "gt", "right": 100}]}}),
            NodeSchema(id="http_1", type="api_call", operation="http.request", label="Fetch URL",
                       description="GET request to the target URL.",
                       config={"method": "GET", "url": "{{nodes.set_1.output.target_url}}", "timeout_seconds": 15}),
            NodeSchema(id="end_fetched", type="end", operation="core.end", label="Return Response",
                       description="Returns the HTTP status and body.",
                       config={"output": {"status": "{{nodes.http_1.output.status_code}}",
                                          "body": "{{nodes.http_1.output.body}}"}}),
            NodeSchema(id="end_skipped", type="end", operation="core.end", label="Skip Small Amounts",
                       description="Returns without calling the URL.",
                       config={"output": {"skipped": True, "amount": "{{nodes.set_1.output.amount}}"}}),
        ],
        edges=[
            EdgeSchema(id="e1", source="trigger_1", target="set_1"),
            EdgeSchema(id="e2", source="set_1", target="if_1"),
            EdgeSchema(id="e3", source="if_1", target="http_1", source_port="true", label="true"),
            EdgeSchema(id="e4", source="http_1", target="end_fetched"),
            EdgeSchema(id="e5", source="if_1", target="end_skipped", source_port="false", label="false"),
        ],
        start_nodes=["trigger_1"],
        end_nodes=["end_fetched", "end_skipped"],
    )
