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
}
