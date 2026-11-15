"""LIVE provider tests (real inference, billed). Run with:  python -m pytest -m live tests/test_ai_live.py -s

Each provider is skipped unless its key is set: OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY (backend/.env
is loaded by app.core.config; the default test run blanks them, so these tests read the keys from the
LIVE_* variables captured in conftest before blanking). Results are printed with the provider and model so the
report can state exactly what was verified live.
"""

from __future__ import annotations

import os

import pytest
from builders import edge, node, workflow
from fastapi.testclient import TestClient

from app.core.config import get_settings

pytestmark = pytest.mark.live

LIVE = {
    "openai": ("OPENAI_API_KEY", os.environ.get("LIVE_OPENAI_API_KEY", ""), "gpt-6.1-sol"),
    "anthropic": ("ANTHROPIC_API_KEY", os.environ.get("LIVE_ANTHROPIC_API_KEY", ""), "claude-sonnet-5-5"),
    # gemini-3.5-flash-lite: the Gemini model with free-tier quota left on the verification key (3.5-flash hit
    # its daily free-tier limit during Milestone 2 verification). Change freely when quota allows.
    "gemini": ("GEMINI_API_KEY", os.environ.get("LIVE_GEMINI_API_KEY", ""), "gemini-3.5-flash-lite"),
}
SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "category": {"type": "string", "enum": ["billing", "technical", "account", "general"]},
}, "required": ["summary", "category"]}


def _enable(monkeypatch, provider):
    setting, key, model = LIVE[provider]
    if not key:
        pytest.skip(f"{provider}: no live key (set {setting} in backend/.env)")
    settings = get_settings()
    monkeypatch.setattr(settings, setting, key)
    monkeypatch.setattr(settings, "AI_ALLOW_PLATFORM_KEYS", True)
    return model


def _run(client, headers, definition, payload):
    wf = client.post("/api/workflows", json={"definition": definition}, headers=headers).json()
    assert wf["validation"]["valid"], wf["validation"]["issues"]
    res = client.post(f"/api/workflows/{wf['id']}/run?wait=true", json={"input": payload}, headers=headers)
    return res.json()


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_live_ai_generate_structured(app_client: TestClient, auth_headers, monkeypatch, provider):
    model = _enable(monkeypatch, provider)
    detail = _run(app_client, auth_headers, workflow("live gen", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("ai_generate_1", "ai.generate", {
            "model": {"provider": provider, "model": model, "max_output_tokens": 1024, "timeout_seconds": 90},
            "system_prompt": "Classify customer support messages.",
            "prompt": "Write a one-sentence summary and classify the message.",
            "inputs": {"message": "{{trigger.message}}"}, "output_format": "json", "output_schema": SCHEMA}),
        node("end_1", "core.end", {"output": "{{nodes.ai_generate_1.output.result}}"}),
    ], [edge("e1", "manual_trigger_1", "ai_generate_1"), edge("e2", "ai_generate_1", "end_1")]),
        {"message": "The customer says their payment was deducted twice."})
    print(f"\nLIVE {provider}/{model} ai.generate ->", detail["status"], detail.get("output"))
    assert detail["status"] == "completed", detail
    assert detail["output"]["category"] == "billing" and isinstance(detail["output"]["summary"], str)
    gen = next(n for n in detail["nodes"] if n["node_id"] == "ai_generate_1")
    assert gen["output"]["usage"]["total_tokens"], "provider should report usage"


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_live_agent_uses_calculator_tool(app_client: TestClient, auth_headers, monkeypatch, provider):
    model = _enable(monkeypatch, provider)
    detail = _run(app_client, auth_headers, workflow("live agent", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("agent_1", "ai.agent", {
            "model": {"provider": provider, "model": model, "max_output_tokens": 2048, "timeout_seconds": 90},
            "instructions": "You analyse order records. You MUST use the data_aggregate tool to total the order "
                            "amounts and the calculator tool to apply the 10% discount. Never compute mentally.",
            "task": "Return the total order amount and the total after a 10% discount.",
            "inputs": {"orders": "{{trigger.orders}}"}, "tools": ["data_aggregate", "calculator"],
            "output_schema": {"type": "object", "properties": {"total": {"type": "number"},
                                                               "discounted_total": {"type": "number"}},
                              "required": ["total", "discounted_total"]},
            "limits": {"max_iterations": 6, "max_tool_calls": 8, "timeout_seconds": 240}}),
        node("end_1", "core.end", {"output": "{{nodes.agent_1.output.result}}"}),
    ], [edge("e1", "manual_trigger_1", "agent_1"), edge("e2", "agent_1", "end_1")]),
        {"orders": [{"id": 1, "amount": 120.5}, {"id": 2, "amount": 80}, {"id": 3, "amount": 49.5}]})
    agent = next(n for n in detail["nodes"] if n["node_id"] == "agent_1")
    print(f"\nLIVE {provider}/{model} ai.agent ->", detail["status"], detail.get("output"),
          [(t["tool"], t["status"]) for t in (agent.get("output") or {}).get("tool_calls", [])])
    if detail["status"] != "completed":
        print("AGENT ERROR:", agent.get("error"))
    assert detail["status"] == "completed", detail
    assert detail["output"]["total"] == pytest.approx(250) and detail["output"]["discounted_total"] == pytest.approx(225)
    assert any(t["tool"] in {"data_aggregate", "calculator"} and t["status"] == "success"
               for t in agent["output"]["tool_calls"])


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_live_connection_test(provider):
    import asyncio

    from app.ai.providers import test_connection

    _, key, model = LIVE[provider]
    if not key:
        pytest.skip(f"{provider}: no live key")
    result = asyncio.run(test_connection(provider, key))
    print(f"\nLIVE {provider} connection test ->", result)
    assert result.ok and model in (result.models_available or [])


@pytest.mark.parametrize("primary_provider", ["openai", "anthropic"])
def test_live_cross_provider_fallback(app_client: TestClient, auth_headers, monkeypatch, primary_provider):
    """Primary on OpenAI/Anthropic, fallback on Gemini. Whatever the primary does live, the run must complete and
    the routing decision must be recorded honestly: either the primary answered (no fallback), or it failed with an
    availability/billing error and the Gemini fallback answered (fallback_used + reason)."""
    primary_model = _enable(monkeypatch, primary_provider)
    fallback_model = _enable(monkeypatch, "gemini")
    detail = _run(app_client, auth_headers, workflow("live fallback", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("agent_1", "ai.agent", {
            "model": {"provider": primary_provider, "model": primary_model, "max_output_tokens": 1024,
                      "timeout_seconds": 90},
            "fallback_model": {"provider": "gemini", "model": fallback_model, "max_output_tokens": 1024,
                               "timeout_seconds": 90},
            "instructions": "Classify the customer message.", "task": "Classify: {{trigger.message}}",
            "output_schema": SCHEMA, "limits": {"max_iterations": 2, "timeout_seconds": 300}}),
        node("end_1", "core.end", {"output": "{{nodes.agent_1.output}}"}),
    ], [edge("e1", "manual_trigger_1", "agent_1"), edge("e2", "agent_1", "end_1")]),
        {"message": "I was charged twice for my order."})
    agent = next(n for n in detail["nodes"] if n["node_id"] == "agent_1")
    out = agent.get("output") or {}
    print(f"\nLIVE fallback {primary_provider}/{primary_model} -> gemini/{fallback_model}:", detail["status"],
          "used", out.get("provider"), out.get("model"), "fallback_used", out.get("fallback_used"),
          "reason", out.get("fallback_reason"), "error", agent.get("error") and agent["error"]["message"])
    assert detail["status"] == "completed", agent.get("error")
    assert detail["output"]["result"]["category"] == "billing"
    if out["fallback_used"]:
        assert out["provider"] == "gemini" and out["fallback_reason"]
    else:
        assert out["provider"] == primary_provider
