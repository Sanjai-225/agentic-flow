"""Valid example configurations for executable operations.

They are injected into the AI designer prompt so generated configs match the
config models, and ``tests/test_registry_executors.py`` validates each one.
"""

from typing import Any, Dict

EXAMPLE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "core.manual_trigger": {"sample_payload": {"email": "user@example.com", "amount": 120}},
    "core.webhook_trigger": {"method": "POST"},
    "core.set": {
        "fields": [
            {"name": "greeting", "value": "Hello {{trigger.name}}", "type": "string"},
            {"name": "amount", "value": "{{trigger.amount}}", "type": "number"},
        ],
        "keep_input": False,
    },
    "core.json_parse": {"source": "{{nodes.http_1.output.body}}"},
    "core.filter": {
        "items": "{{nodes.http_1.output.body.items}}",
        "conditions": {"combinator": "all", "rules": [{"left": "{{item.status}}", "operator": "eq", "right": "active"}]},
    },
    "core.transform": {"mappings": {"customer.email": "{{trigger.email}}", "total": "{{nodes.set_1.output.amount}}"}},
    "core.if": {
        "conditions": {
            "combinator": "all",
            "rules": [{"left": "{{nodes.set_1.output.amount}}", "operator": "gt", "right": 100}],
        }
    },
    "core.end": {"output": {"status": "{{nodes.http_1.output.status_code}}"}},
    "http.request": {
        "method": "POST",
        "url": "https://api.example.com/items",
        "query": {},
        "headers": {"X-Request-Source": "agentic-flow"},
        "body_type": "json",
        "body": {"name": "{{nodes.set_1.output.greeting}}"},
        "timeout_seconds": 30,
    },
    "ai.generate": {
        "model": {"provider": "gemini", "model": "gemini-3.5-flash", "max_output_tokens": 1024,
                  "timeout_seconds": 60},
        "system_prompt": "You are a support triage assistant.",
        "prompt": "Summarize the customer message in one sentence and classify it.",
        "inputs": {"message": "{{trigger.message}}"},
        "output_format": "json",
        "output_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "category": {"type": "string", "enum": ["billing", "technical", "account", "general"]},
            },
            "required": ["summary", "category"],
        },
    },
    "ai.agent": {
        "model": {"provider": "gemini", "model": "gemini-3.5-flash", "max_output_tokens": 2048,
                  "timeout_seconds": 60},
        "instructions": "You analyse order records. Use the data_aggregate or calculator tool for every calculation.",
        "task": "Compute the total order value and the number of orders.",
        "inputs": {"orders": "{{trigger.orders}}"},
        "tools": ["data_aggregate", "calculator"],
        "output_schema": {
            "type": "object",
            "properties": {"total": {"type": "number"}, "count": {"type": "integer"}},
            "required": ["total", "count"],
        },
        "limits": {"max_iterations": 6, "max_tool_calls": 10, "timeout_seconds": 120},
    },
    "core.form_trigger": {
        "title": "Project enquiry",
        "fields": [
            {"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "budget", "label": "Budget", "type": "number", "min": 0},
        ],
        "success_message": "Thanks, we will be in touch.",
    },
    "core.schedule_trigger": {"mode": "weekdays", "hour": 9, "minute": 0, "timezone": "Europe/Berlin",
                              "enabled": True, "misfire_policy": "skip"},
    "core.switch": {
        "mode": "first",
        "cases": [
            {"key": "billing", "label": "Billing", "conditions": {"combinator": "all", "rules": [
                {"left": "{{nodes.agent_1.output.result.category}}", "operator": "eq", "right": "billing"}]}},
            {"key": "technical", "label": "Technical", "conditions": {"combinator": "all", "rules": [
                {"left": "{{nodes.agent_1.output.result.category}}", "operator": "eq", "right": "technical"}]}},
        ],
    },
    "core.merge": {"inputs": 2, "mode": "by_input", "require": "any"},
    "core.loop": {"items": "{{trigger.orders}}", "max_items": 100, "on_item_error": "stop", "timeout_seconds": 300},
    "core.datetime": {"operation": "add", "value": "{{trigger.created_at}}", "amount": 7, "unit": "days",
                      "timezone": "UTC"},
    "core.array": {"items": "{{trigger.orders}}", "operation": "sum", "field": "amount"},
}
