"""Canonical workflow definitions used across tests."""

from typing import Any, Dict, List, Optional


def node(id_: str, operation: str, config: Optional[Dict[str, Any]] = None, label: Optional[str] = None,
         **extra: Any) -> Dict[str, Any]:
    return {"id": id_, "operation": operation, "label": label or id_, "config": config or {},
            "ui": {"position": {"x": 0, "y": 0}}, **extra}


def edge(id_: str, source: str, target: str, source_port: str = "main") -> Dict[str, Any]:
    return {"id": id_, "source": source, "target": target, "source_port": source_port}


def workflow(name: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"schema_version": 2, "workflow_id": "draft", "workflow_name": name, "nodes": nodes, "edges": edges}


def demo_workflow(base_url: str, threshold: int = 100) -> Dict[str, Any]:
    """Manual Trigger -> Set Variable -> If/Else -> HTTP Request (true) -> End / End (false)."""
    return workflow(
        "Demo: conditional HTTP",
        [
            node("trigger", "core.manual_trigger", {"sample_payload": {"name": "Ada", "amount": 150}}, "Start"),
            node("set_vars", "core.set", {"fields": [
                {"name": "customer", "value": "{{trigger.name}}", "type": "string"},
                {"name": "amount", "value": "{{trigger.amount}}", "type": "number"},
                {"name": "greeting", "value": "Hello {{trigger.name}}!", "type": "auto"},
            ]}, "Set Variables"),
            node("check_amount", "core.if", {"conditions": {"combinator": "all", "rules": [
                {"left": "{{nodes.set_vars.output.amount}}", "operator": "gt", "right": threshold},
            ]}}, "Amount > threshold?"),
            node("notify", "http.request", {
                "method": "POST",
                "url": f"{base_url}/echo",
                "query": {"source": "agentic-flow"},
                "headers": {"X-Customer": "{{nodes.set_vars.output.customer}}"},
                "body_type": "json",
                "body": {"amount": "{{nodes.set_vars.output.amount}}",
                         "greeting": "{{nodes.set_vars.output.greeting}}"},
                "timeout_seconds": 10,
            }, "Notify API"),
            node("end_high", "core.end", {"output": {
                "branch": "high", "status": "{{nodes.notify.output.status_code}}",
                "echo": "{{nodes.notify.output.body}}"}}, "End (high)"),
            node("end_low", "core.end", {"output": {"branch": "low", "amount": "{{input.amount}}"}}, "End (low)"),
        ],
        [
            edge("e1", "trigger", "set_vars"),
            edge("e2", "set_vars", "check_amount"),
            edge("e3", "check_amount", "notify", "true"),
            edge("e4", "notify", "end_high"),
            edge("e5", "check_amount", "end_low", "false"),
        ],
    )


def single_node_after_trigger(op: str, config: Dict[str, Any], **node_extra: Any) -> Dict[str, Any]:
    return workflow(
        f"Single {op}",
        [node("trigger", "core.manual_trigger"), node("step", op, config, **node_extra)],
        [edge("e1", "trigger", "step")],
    )
