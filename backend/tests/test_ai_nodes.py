"""AI Generate, AI Agent, provider routing, credentials and tool security (Milestone 2, Phases 2-4).

ALL inference in this file is MOCKED with the scripted fake chat model (tests/fake_llm.py). The real router,
structured-output, LangGraph agent, tool registry, executor, runner and persistence code run unchanged.
Live provider tests are in test_ai_live.py (pytest -m live).
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pytest
from pydantic import ValidationError
from builders import edge, node, workflow
from conftest import register, wait_for_execution
from fake_llm import Script, ai, ai_json, install
from fastapi.testclient import TestClient

from app.ai.tools import get_tool_registry
from app.core.config import get_settings

PLATFORM_KEYS = {"GEMINI_API_KEY": "platform-gemini-KEY-0123456789",
                 "OPENAI_API_KEY": "platform-openai-KEY-0123456789",
                 "ANTHROPIC_API_KEY": "platform-anthropic-KEY-0123456789"}

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "category": {"type": "string", "enum": ["billing", "technical", "account", "general"]},
        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["summary", "category", "priority"],
}


class FakeHTTPError(Exception):
    """Stand-in for a provider SDK error carrying an HTTP status code."""

    def __init__(self, status_code: int, message: str = "provider error") -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.fixture
def platform_keys(monkeypatch):
    settings = get_settings()
    for name, value in PLATFORM_KEYS.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "AI_ALLOW_PLATFORM_KEYS", True)
    monkeypatch.setattr(settings, "AI_MODEL_MAX_RETRIES", 1)
    return settings


def model(provider: str = "gemini", name: str = "gemini-3.8-flash", **extra: Any) -> Dict[str, Any]:
    return {"provider": provider, "model": name, "max_output_tokens": 512, "timeout_seconds": 5, **extra}


def gen_workflow(config: Dict[str, Any]) -> Dict[str, Any]:
    return workflow("ai gen", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("ai_generate_1", "ai.generate", config),
        node("end_1", "core.end", {"output": "{{nodes.ai_generate_1.output.result}}"}),
    ], [edge("e1", "manual_trigger_1", "ai_generate_1"), edge("e2", "ai_generate_1", "end_1")])


def agent_workflow(config: Dict[str, Any]) -> Dict[str, Any]:
    return workflow("agent", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("agent_1", "ai.agent", config),
        node("end_1", "core.end", {"output": "{{nodes.agent_1.output.result}}"}),
    ], [edge("e1", "manual_trigger_1", "agent_1"), edge("e2", "agent_1", "end_1")])


def run_wf(client: TestClient, headers, definition, payload=None) -> Dict[str, Any]:
    res = client.post("/api/workflows", json={"definition": definition}, headers=headers)
    assert res.status_code == 201, res.text
    wf = res.json()
    assert wf["validation"]["valid"], wf["validation"]["issues"]
    run = client.post(f"/api/workflows/{wf['id']}/run?wait=true", json={"input": payload or {}}, headers=headers)
    assert run.status_code == 200, run.text
    return run.json()


def node_run(detail, node_id):
    return next(n for n in detail["nodes"] if n["node_id"] == node_id)


# =============================================================================================== AI Generate
def test_ai_generate_structured_output_is_typed_and_usage_recorded(app_client, auth_headers, monkeypatch,
                                                                   platform_keys):
    script = install(monkeypatch, Script({"gemini-3.8-flash": [
        ai_json({"summary": "Payment deducted twice", "category": "billing", "priority": "high"},
                input_tokens=40, output_tokens=12)]}))
    detail = run_wf(app_client, auth_headers, gen_workflow({
        "model": model(), "system_prompt": "Classify support messages.", "prompt": "Classify this message.",
        "inputs": {"message": "{{trigger.message}}"}, "output_format": "json", "output_schema": CLASSIFY_SCHEMA,
    }), {"message": "The customer says their payment was deducted twice."})
    assert detail["status"] == "completed", detail
    assert detail["output"] == {"summary": "Payment deducted twice", "category": "billing", "priority": "high"}
    gen = node_run(detail, "ai_generate_1")
    assert gen["output"]["provider"] == "gemini" and gen["output"]["model"] == "gemini-3.8-flash"
    assert gen["output"]["usage"] == {"input_tokens": 40, "output_tokens": 12, "total_tokens": 52}
    assert gen["metadata"]["ai"]["credential_source"] == "platform"
    # the mapped input really reached the model (input mapping through the existing expression engine)
    human = script.calls[0]["messages"][-1].content
    assert "deducted twice" in human and '"message"' in human
    usage = app_client.get(f"/api/ai/usage?execution_id={detail['id']}", headers=auth_headers).json()
    assert len(usage) == 1 and usage[0]["total_tokens"] == 52 and usage[0]["status"] == "success"
    assert usage[0]["node_id"] == "ai_generate_1" and usage[0]["operation"] == "ai.generate"


def test_ai_generate_text_mode(app_client, auth_headers, monkeypatch, platform_keys):
    install(monkeypatch, Script({"gemini-3.8-flash": [ai("A short summary.")]}))
    detail = run_wf(app_client, auth_headers, gen_workflow({"model": model(), "prompt": "Summarise {{trigger.t}}"}),
                    {"t": "long text"})
    assert detail["status"] == "completed" and detail["output"] == "A short summary."


def test_ai_generate_repairs_invalid_json_then_succeeds(app_client, auth_headers, monkeypatch, platform_keys):
    script = install(monkeypatch, Script({"gemini-3.8-flash": [
        ai_json({"summary": "x", "category": "nonsense", "priority": "high"}),
        ai_json({"summary": "x", "category": "general", "priority": "low"}),
    ]}))
    detail = run_wf(app_client, auth_headers, gen_workflow({
        "model": model(), "prompt": "Classify", "output_format": "json", "output_schema": CLASSIFY_SCHEMA,
        "max_repair_attempts": 1}))
    assert detail["status"] == "completed" and detail["output"]["category"] == "general"
    repair_prompt = script.calls[1]["messages"][-1].content
    assert "did not match the required JSON schema" in repair_prompt and "category" in repair_prompt
    trace = node_run(detail, "ai_generate_1")["metadata"]["trace"]
    assert [t["valid"] for t in trace] == [False, True]


def test_ai_generate_invalid_output_after_repairs_fails_clearly(app_client, auth_headers, monkeypatch,
                                                                platform_keys):
    install(monkeypatch, Script({"gemini-3.8-flash": [ai("not json"), ai_json({"summary": 1})]}))
    detail = run_wf(app_client, auth_headers, gen_workflow({
        "model": model(), "prompt": "Classify", "output_format": "json", "output_schema": CLASSIFY_SCHEMA,
        "max_repair_attempts": 1}))
    assert detail["status"] == "failed"
    err = node_run(detail, "ai_generate_1")["error"]
    assert err["category"] == "STRUCTURED_OUTPUT_INVALID" and "after 2 attempt(s)" in err["message"]


def test_missing_credentials_fail_before_any_model_call(app_client, auth_headers, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    script = install(monkeypatch, Script({}))
    detail = run_wf(app_client, auth_headers, gen_workflow({"model": model(), "prompt": "hi"}))
    err = node_run(detail, "ai_generate_1")["error"]
    assert err["category"] == "MISSING_CREDENTIALS" and err["field"] == "model.credential_id"
    assert script.calls == []


def test_platform_keys_can_be_disabled(app_client, auth_headers, monkeypatch, platform_keys):
    monkeypatch.setattr(platform_keys, "AI_ALLOW_PLATFORM_KEYS", False)
    install(monkeypatch, Script({}))
    detail = run_wf(app_client, auth_headers, gen_workflow({"model": model(), "prompt": "hi"}))
    err = node_run(detail, "ai_generate_1")["error"]
    assert err["category"] == "MISSING_CREDENTIALS" and "AI_ALLOW_PLATFORM_KEYS=false" in err["message"]


@pytest.mark.parametrize("bad_model,fragment", [
    ({"provider": "gemini", "model": "gemini-0-imaginary"}, "is not a supported gemini model"),
    ({"provider": "anthropic", "model": "claude-opus-5-5", "temperature": 0.3}, "does not accept a temperature"),
    ({"provider": "openai", "model": "gpt-6.1-sol", "max_output_tokens": 999_999}, "less than or equal"),
    ({"provider": "mistral", "model": "x"}, "provider"),
])
def test_unsupported_provider_model_or_option_rejected_before_run(app_client, auth_headers, bad_model, fragment):
    res = app_client.post("/api/workflows/validate", json={"definition": gen_workflow(
        {"model": bad_model, "prompt": "hi"})}, headers=auth_headers)
    issues = [i for i in res.json()["issues"] if i["node_id"] == "ai_generate_1"]
    assert issues and any(fragment in i["message"] for i in issues), issues


# =============================================================================================== credentials
def test_provider_credentials_are_encrypted_masked_updatable_and_isolated(app_client, auth_headers, monkeypatch):
    secret = "sk-user-openai-SECRET-abcdefgh9999"
    res = app_client.post("/api/credentials", json={"type": "openai_api_key", "name": "My OpenAI",
                                                    "data": {"api_key": secret}}, headers=auth_headers)
    assert res.status_code == 201, res.text
    cred = res.json()
    assert secret not in res.text and cred["hints"] == {"api_key": "••••9999"} and cred["provider"] == "openai"
    listing = app_client.get("/api/credentials", headers=auth_headers)
    assert secret not in listing.text

    # rename keeps the stored key; replacing the key changes the masked hint
    res = app_client.put(f"/api/credentials/{cred['id']}", json={"name": "Renamed"}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["name"] == "Renamed" and res.json()["hints"]["api_key"] == "••••9999"
    res = app_client.put(f"/api/credentials/{cred['id']}", json={"data": {"api_key": "sk-new-key-XYZ-12345678"}},
                         headers=auth_headers)
    assert res.json()["hints"]["api_key"] == "••••5678" and res.json()["updated_at"]

    # connection test performs the provider call with the decrypted key (provider client mocked here)
    seen = {}

    async def fake_test(provider, api_key, timeout=20.0):
        from app.ai.providers import ConnectionResult
        seen.update(provider=provider, key=api_key)
        return ConnectionResult(True, "OpenAI accepted the key.", None, ["gpt-6.1-sol"])

    monkeypatch.setattr("app.ai.providers.test_connection", fake_test)
    res = app_client.post(f"/api/credentials/{cred['id']}/test", headers=auth_headers)
    assert res.status_code == 200 and res.json()["ok"] is True and seen == {"provider": "openai",
                                                                           "key": "sk-new-key-XYZ-12345678"}
    assert "sk-new-key" not in res.text

    # another user can neither see, update, test nor use it
    other = register(app_client)
    assert app_client.put(f"/api/credentials/{cred['id']}", json={"name": "x"}, headers=other).status_code == 404
    assert app_client.post(f"/api/credentials/{cred['id']}/test", headers=other).status_code == 404
    res = app_client.post("/api/workflows/validate", json={"definition": gen_workflow(
        {"model": model("openai", "gpt-6.1-sol", credential_id=cred["id"]), "prompt": "hi"})}, headers=other)
    assert any(i["category"] == "MISSING_CREDENTIALS" for i in res.json()["issues"])


def test_http_credentials_have_no_fake_connection_test(app_client, auth_headers):
    cred = app_client.post("/api/credentials", json={"type": "http_bearer", "name": "t", "data": {"token": "abc12345"}},
                           headers=auth_headers).json()
    res = app_client.post(f"/api/credentials/{cred['id']}/test", headers=auth_headers)
    assert res.status_code == 400 and "not available" in res.json()["detail"]


def test_user_credential_key_is_used_and_scrubbed_from_everything(app_client, auth_headers, monkeypatch):
    secret = "AIzaUSERgeminiKEYabcdefghijklmnop123456"
    cred = app_client.post("/api/credentials", json={"type": "gemini_api_key", "name": "g",
                                                     "data": {"api_key": secret}}, headers=auth_headers).json()
    # A misbehaving provider echoes the key back; it must never be persisted or returned.
    script = install(monkeypatch, Script({"gemini-3.8-flash": [ai(f"echo {secret}")]}))
    detail = run_wf(app_client, auth_headers, gen_workflow({"model": model(credential_id=cred["id"]), "prompt": "x"}))
    assert script.keys_seen == [secret]
    gen = node_run(detail, "ai_generate_1")
    assert gen["metadata"]["ai"]["credential_source"] == "user"
    full = app_client.get(f"/api/executions/{detail['id']}", headers=auth_headers).text
    assert secret not in full and "***redacted***" in full


def test_ai_provider_catalogue_endpoint(app_client, auth_headers, platform_keys):
    providers = {p["id"]: p for p in app_client.get("/api/ai/providers", headers=auth_headers).json()}
    assert set(providers) == {"openai", "anthropic", "gemini"}
    assert {"gpt-6.1-sol", "gpt-6-astra"} <= {m["model"] for m in providers["openai"]["models"]}
    assert {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"} <= {m["model"]
                                                                             for m in providers["anthropic"]["models"]}
    assert providers["gemini"]["platform_key_available"] is True
    text = app_client.get("/api/ai/providers", headers=auth_headers).text
    assert PLATFORM_KEYS["GEMINI_API_KEY"] not in text
    assert app_client.get("/api/ai/providers").status_code == 401


# =============================================================================================== routing
def fallback_agent(**limits: Any) -> Dict[str, Any]:
    return {"model": model("openai", "gpt-6.1-sol"), "fallback_model": model("anthropic", "claude-sonnet-5-5"),
            "instructions": "Answer briefly.", "task": "Say hi", "limits": {"timeout_seconds": 30, **limits}}


def test_primary_unavailable_falls_back_to_other_provider(app_client, auth_headers, monkeypatch, platform_keys):
    install(monkeypatch, Script({"gpt-6.1-sol": [FakeHTTPError(503), FakeHTTPError(503)],
                                 "claude-sonnet-5-5": [ai("Hi from fallback")]}))
    detail = run_wf(app_client, auth_headers, agent_workflow(fallback_agent()))
    assert detail["status"] == "completed" and detail["output"] == "Hi from fallback"
    out = node_run(detail, "agent_1")["output"]
    assert out["provider"] == "anthropic" and out["model"] == "claude-sonnet-5-5" and out["fallback_used"] is True
    assert "MODEL_UNAVAILABLE" in out["fallback_reason"]
    calls = node_run(detail, "agent_1")["metadata"]["model_calls"]
    assert [(c["role"], c["status"]) for c in calls] == [("primary", "error"), ("primary", "error"),
                                                          ("fallback", "success")]


def test_auth_failure_never_falls_back(app_client, auth_headers, monkeypatch, platform_keys):
    script = install(monkeypatch, Script({"gpt-6.1-sol": [FakeHTTPError(401, "invalid api key")],
                                          "claude-sonnet-5-5": [ai("should not be used")]}))
    detail = run_wf(app_client, auth_headers, agent_workflow(fallback_agent()))
    err = node_run(detail, "agent_1")["error"]
    assert err["category"] == "MODEL_AUTH"
    assert [c["model"] for c in script.calls] == ["gpt-6.1-sol"]


def test_fallback_unavailable_reports_error(app_client, auth_headers, monkeypatch, platform_keys):
    install(monkeypatch, Script({"gpt-6.1-sol": [FakeHTTPError(429)] * 2,
                                 "claude-sonnet-5-5": [FakeHTTPError(529), FakeHTTPError(500)]}))
    detail = run_wf(app_client, auth_headers, agent_workflow(fallback_agent()))
    err = node_run(detail, "agent_1")["error"]
    assert err["category"] == "MODEL_UNAVAILABLE" and "anthropic/claude-sonnet-5-5" in err["message"]
    assert len(err["details"]["model_calls"]) == 4


def test_inference_timeout_is_classified(app_client, auth_headers, monkeypatch, platform_keys):
    monkeypatch.setattr(platform_keys, "AI_MODEL_MAX_RETRIES", 0)
    install(monkeypatch, Script({"gemini-3.8-flash": [("sleep", 3), ai("late")]}))
    cfg = {"model": model(timeout_seconds=1), "prompt": "x", "max_retries": 0}
    detail = run_wf(app_client, auth_headers, gen_workflow(cfg))
    assert node_run(detail, "ai_generate_1")["error"]["category"] == "MODEL_TIMEOUT"


def test_ai_generate_never_falls_back(app_client, auth_headers):
    res = app_client.post("/api/workflows/validate", json={"definition": gen_workflow({
        "model": model(), "prompt": "x", "fallback_model": model("openai", "gpt-6.1-sol")})}, headers=auth_headers)
    assert any("fallback_model" in (i.get("field") or "") for i in res.json()["issues"])


# =============================================================================================== agent
def test_agent_task_1_classification_structured_output(app_client, auth_headers, monkeypatch, platform_keys):
    schema = {**CLASSIFY_SCHEMA, "properties": {**CLASSIFY_SCHEMA["properties"],
                                                "next_action": {"type": "string"}},
              "required": CLASSIFY_SCHEMA["required"] + ["next_action"]}
    install(monkeypatch, Script({"gemini-3.8-flash": [
        ai("The message is about a duplicate charge; refund it."),
        ai_json({"summary": "Duplicate charge", "category": "billing", "priority": "high",
                 "next_action": "Refund the duplicate payment"}),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "You are a support classification agent.",
        "task": "Analyse the message.", "inputs": {"message": "{{trigger.message}}"}, "output_schema": schema,
    }), {"message": "I was charged twice!"})
    assert detail["status"] == "completed", detail
    assert detail["output"]["category"] == "billing" and detail["output"]["next_action"]
    out = node_run(detail, "agent_1")["output"]
    assert out["iterations"] == 1 and out["tool_calls"] == []


def test_agent_task_2_executes_permitted_calculator_tool(app_client, auth_headers, monkeypatch, platform_keys):
    script = install(monkeypatch, Script({"gemini-3.8-flash": [
        ai(tool_calls=[{"name": "calculator", "args": {"expression": "120.5 + 80 + 49.5"}}]),
        lambda messages, tools: ai("The total is " + messages[-1].content),
        ai_json({"total": 250, "count": 3}),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "Use the calculator for arithmetic.", "task": "Total the orders.",
        "inputs": {"orders": "{{trigger.orders}}"}, "tools": ["calculator"],
        "output_schema": {"type": "object", "properties": {"total": {"type": "number"}, "count": {"type": "integer"}},
                          "required": ["total", "count"]},
        "limits": {"max_iterations": 4},
    }), {"orders": [{"amount": 120.5}, {"amount": 80}, {"amount": 49.5}]})
    assert detail["status"] == "completed", detail
    assert detail["output"] == {"total": 250, "count": 3}
    out = node_run(detail, "agent_1")["output"]
    assert out["tool_calls"][0]["tool"] == "calculator" and out["tool_calls"][0]["status"] == "success"
    assert '"result": 250' in out["tool_calls"][0]["result_summary"]
    # the real tool result was fed back to the model
    assert '"result": 250' in script.calls[1]["messages"][-1].content
    assert script.calls[0]["tools"] == ["calculator"]  # only the allowed tool was bound


def test_agent_multiple_tool_calls_and_state_updates(app_client, auth_headers, monkeypatch, platform_keys):
    install(monkeypatch, Script({"gemini-3.8-flash": [
        ai(tool_calls=[{"name": "data_aggregate", "args": {"records": [{"v": 2}, {"v": 3}], "operation": "sum",
                                                           "field": "v"}, "id": "a"}]),
        ai(tool_calls=[{"name": "calculator", "args": {"expression": "5 * 1.2"}, "id": "b"},
                       {"name": "datetime", "args": {"operation": "diff", "value": "2026-01-01",
                                                     "other": "2026-01-31", "unit": "days"}, "id": "c"}]),
        ai("Sum 5, with markup 6, 30 days."),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "Use tools.", "task": "Compute.",
        "tools": ["data_aggregate", "calculator", "datetime"]}))
    assert detail["status"] == "completed", detail
    out = node_run(detail, "agent_1")["output"]
    assert [t["tool"] for t in out["tool_calls"]] == ["data_aggregate", "calculator", "datetime"]
    assert all(t["status"] == "success" for t in out["tool_calls"]) and out["iterations"] == 3
    summaries = " ".join(t["result_summary"] for t in out["tool_calls"])
    assert '"result": 5' in summaries and '"result": 6' in summaries and '"result": 30' in summaries


def _spy_tool(monkeypatch, tool_id: str) -> Dict[str, int]:
    calls = {"n": 0}
    tool = get_tool_registry().get(tool_id)
    original = tool.execute

    async def spy(args, ctx):
        calls["n"] += 1
        return await original(args, ctx)

    monkeypatch.setattr(tool, "execute", spy)
    return calls


def test_unknown_and_unauthorized_tools_are_never_executed(app_client, auth_headers, monkeypatch, platform_keys):
    spy = _spy_tool(monkeypatch, "http_get")
    install(monkeypatch, Script({"gemini-3.8-flash": [
        ai(tool_calls=[{"name": "delete_everything", "args": {}, "id": "x"},
                       {"name": "http_get", "args": {"url": "https://example.com"}, "id": "y"}]),
        ai("Done without those tools."),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"]}))
    assert detail["status"] == "completed"
    calls = node_run(detail, "agent_1")["output"]["tool_calls"]
    assert [(c["tool"], c["status"]) for c in calls] == [("delete_everything", "rejected"), ("http_get", "rejected")]
    assert "Unknown tool" in calls[0]["reason"] and "not enabled for this agent" in calls[1]["reason"]
    assert spy["n"] == 0


def test_repeated_unauthorized_tool_calls_stop_the_agent(app_client, auth_headers, monkeypatch, platform_keys):
    bad = ai(tool_calls=[{"name": "http_get", "args": {"url": "https://example.com"}}])
    install(monkeypatch, Script({"gemini-3.8-flash": [bad, bad, bad]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"],
        "limits": {"max_tool_errors": 3}}))
    err = node_run(detail, "agent_1")["error"]
    assert err["category"] == "TOOL_NOT_ALLOWED" and err["details"]["agent_trace"]


def test_invalid_tool_arguments_are_rejected(app_client, auth_headers, monkeypatch, platform_keys):
    spy = _spy_tool(monkeypatch, "calculator")
    bad = ai(tool_calls=[{"name": "calculator", "args": {"expression": "1+1", "evil": True}}])
    install(monkeypatch, Script({"gemini-3.8-flash": [bad, bad]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"],
        "limits": {"max_tool_errors": 2}}))
    err = node_run(detail, "agent_1")["error"]
    assert err["category"] == "TOOL_ARGS_INVALID" and "evil" in err["message"]
    assert spy["n"] == 0


def test_tool_failure_is_reported_to_model_then_agent_recovers(app_client, auth_headers, monkeypatch,
                                                                platform_keys):
    install(monkeypatch, Script({"gemini-3.8-flash": [
        ai(tool_calls=[{"name": "calculator", "args": {"expression": "1/0"}}]),
        lambda messages, tools: ai("Division by zero is undefined." if "Division by zero" in messages[-1].content
                                   else "unexpected"),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"]}))
    assert detail["status"] == "completed" and detail["output"] == "Division by zero is undefined."
    assert node_run(detail, "agent_1")["output"]["tool_calls"][0]["status"] == "error"


def test_tool_timeout(app_client, auth_headers, monkeypatch, platform_keys):
    tool = get_tool_registry().get("calculator")

    async def slow(args, ctx):
        import asyncio
        await asyncio.sleep(5)
        return {"expression": "x", "result": 1}

    monkeypatch.setattr(tool, "execute", slow)
    call = ai(tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}}])
    install(monkeypatch, Script({"gemini-3.8-flash": [call]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"],
        "limits": {"tool_timeout_seconds": 0.2, "max_tool_errors": 1}}))
    assert node_run(detail, "agent_1")["error"]["category"] == "TOOL_TIMEOUT"


def test_iteration_limit_is_enforced(app_client, auth_headers, monkeypatch, platform_keys):
    call = ai(tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}}])
    install(monkeypatch, Script({"gemini-3.8-flash": [call] * 5}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"],
        "limits": {"max_iterations": 3, "max_tool_calls": 10}}))
    err = node_run(detail, "agent_1")["error"]
    assert err["category"] == "ITERATION_LIMIT" and "3 model iterations" in err["message"]


def test_tool_call_limit_is_enforced(app_client, auth_headers, monkeypatch, platform_keys):
    call = ai(tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": str(i)} for i in range(3)])
    install(monkeypatch, Script({"gemini-3.8-flash": [call]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"],
        "limits": {"max_tool_calls": 2}}))
    assert node_run(detail, "agent_1")["error"]["category"] == "ITERATION_LIMIT"


def test_token_budget_is_enforced(app_client, auth_headers, monkeypatch, platform_keys):
    call = ai(tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}}], input_tokens=300,
              output_tokens=50)
    install(monkeypatch, Script({"gemini-3.8-flash": [call, call]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["calculator"],
        "limits": {"max_total_tokens": 300}}))
    assert node_run(detail, "agent_1")["error"]["category"] == "USAGE_LIMIT"


def test_input_size_limit_is_enforced(app_client, auth_headers, monkeypatch, platform_keys):
    script = install(monkeypatch, Script({}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "{{trigger.big}}", "limits": {"max_input_chars": 200}}),
        {"big": "y" * 500})
    assert node_run(detail, "agent_1")["error"]["category"] == "USAGE_LIMIT" and script.calls == []


def test_overall_agent_timeout(app_client, auth_headers, monkeypatch, platform_keys):
    install(monkeypatch, Script({"gemini-3.8-flash": [("sleep", 3), ai("late")]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(timeout_seconds=10), "instructions": "x", "task": "y", "limits": {"timeout_seconds": 1}}))
    assert node_run(detail, "agent_1")["error"]["category"] == "TIMEOUT"


def test_agent_cancellation_propagates(app_client, auth_headers, monkeypatch, platform_keys):
    install(monkeypatch, Script({"gemini-3.8-flash": [("sleep", 8), ai("late")]}))
    res = app_client.post("/api/workflows", json={"definition": agent_workflow({
        "model": model(timeout_seconds=30), "instructions": "x", "task": "y"})}, headers=auth_headers)
    wf_id = res.json()["id"]
    exe = app_client.post(f"/api/workflows/{wf_id}/run", json={"input": {}}, headers=auth_headers).json()
    deadline = time.time() + 5
    while time.time() < deadline:
        status = app_client.get(f"/api/executions/{exe['execution_id']}", headers=auth_headers).json()
        if any(n["node_id"] == "agent_1" and n["status"] == "running" for n in status["nodes"]):
            break
        time.sleep(0.05)
    t0 = time.time()
    assert app_client.post(f"/api/executions/{exe['execution_id']}/cancel", headers=auth_headers).status_code == 200
    final = wait_for_execution(app_client, auth_headers, exe["execution_id"], timeout=6)
    assert final["status"] == "cancelled" and time.time() - t0 < 5


def test_agent_trace_redacts_sensitive_arguments(app_client, auth_headers, monkeypatch, platform_keys,
                                                 http_server):
    install(monkeypatch, Script({"gemini-3.8-flash": [
        ai(tool_calls=[{"name": "http_get", "args": {"url": f"{http_server}/json",
                                                     "query": {"api_key": "super-secret-value", "q": "x"}}}]),
        ai("fetched"),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["http_get"]}))
    assert detail["status"] == "completed", detail
    full = app_client.get(f"/api/executions/{detail['id']}", headers=auth_headers).text
    assert "super-secret-value" not in full
    call = node_run(detail, "agent_1")["output"]["tool_calls"][0]
    assert call["status"] == "success" and call["args"]["query"]["api_key"] == "***redacted***"


def test_http_tool_blocks_private_networks(app_client, auth_headers, monkeypatch, platform_keys):
    monkeypatch.setattr(platform_keys, "HTTP_ALLOW_PRIVATE_NETWORKS", False)
    install(monkeypatch, Script({"gemini-3.8-flash": [
        ai(tool_calls=[{"name": "http_get", "args": {"url": "http://127.0.0.1:1/admin"}}]),
        lambda messages, tools: ai("blocked" if "private or local network" in messages[-1].content else "??"),
    ]}))
    detail = run_wf(app_client, auth_headers, agent_workflow({
        "model": model(), "instructions": "x", "task": "y", "tools": ["http_get"]}))
    assert detail["output"] == "blocked"


def test_same_agent_node_type_two_configurations_are_independent():
    """Workflow C/D requirement: one node type, different tasks via configuration only."""
    from app.registry.configs import AgentConfig

    classify = AgentConfig.model_validate({"model": model(), "instructions": "Classify", "output_schema": CLASSIFY_SCHEMA})
    compute = AgentConfig.model_validate({"model": model("anthropic", "claude-haiku-5-5"), "instructions": "Compute",
                                          "tools": ["calculator", "data_aggregate"]})
    assert classify.tools == [] and compute.tools == ["calculator", "data_aggregate"]
    with pytest.raises(ValidationError):
        AgentConfig.model_validate({"model": model(), "instructions": "x", "tools": ["shell_exec"]})
