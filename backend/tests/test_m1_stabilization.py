"""Regression tests for the Milestone 1 fix list (Milestone 2, Phase 0).

(a) predictable node ids + "Did you mean ...?" suggestions
(c) no placeholder Set fields; empty values validated
(d) understandable number/type conversion errors
(e) friendly, secret-free Gemini errors
(f) typed values through End output, Transform mappings and HTTP bodies
((b) output fields before the first run lives in test_output_fields.py)
"""

import io
import json
import socket
import urllib.error

import pytest
from builders import edge, node, workflow
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.expressions import ResolutionScope, evaluate, parse_expression, unknown_node_suggestion
from app.engine.planner import plan_workflow
from app.executors.core import coerce
from app.registry.node_registry import get_default_registry
from app.schemas.workflow import WorkflowSchema
from app.services.llm_errors import GeminiHTTPError, classify_llm_error, scrub_secrets
from app.services.llm_service import LLMConfigurationError, LLMGenerationError, LLMService

FAKE_KEY = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE1234"


def plan(nodes, edges):
    return plan_workflow(WorkflowSchema.model_validate(workflow("t", nodes, edges)))


def trigger(sample=None):
    return node("manual_trigger_1", "core.manual_trigger", {"sample_payload": sample or {}})


# ---------------------------------------------------------------- (a) node id suggestions
def test_planner_suggests_closest_node_id_for_typo():
    p = plan([trigger(), node("set_1", "core.set", {"fields": [{"name": "a", "value": 1}]}),
              node("end_1", "core.end", {"output": "{{nodes.set_l.output.a}}"})],
             [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "end_1")])
    issue = next(i for i in p.errors if i.node_id == "end_1")
    assert issue.category == ErrorCategory.INVALID_MAPPING
    assert "'set_l'" in issue.message and "does not exist" in issue.message
    assert issue.suggestion.startswith("Did you mean 'set_1'?")


def test_planner_lists_upstream_nodes_when_nothing_is_close():
    p = plan([trigger(), node("end_1", "core.end", {"output": "{{nodes.zzzzzz.output}}"})],
             [edge("e1", "manual_trigger_1", "end_1")])
    issue = next(i for i in p.errors if i.node_id == "end_1")
    assert "Existing nodes: manual_trigger_1" in issue.suggestion


def test_runtime_resolver_suggests_closest_node_id():
    scope = ResolutionScope(node_outputs={"http_1": {}}, all_node_ids={"http_1", "end_1"}, ancestors={"http_1"})
    with pytest.raises(NodeExecutionError) as exc:
        evaluate(parse_expression("nodes.http_l.output.body"), scope, "output")
    assert exc.value.error.suggestion.startswith("Did you mean 'http_1'?")


def test_unknown_node_suggestion_is_case_insensitive():
    assert unknown_node_suggestion("SET_1", ["set_1", "if_1"]).startswith("Did you mean 'set_1'?")


# ---------------------------------------------------------------- (c) Set node defaults and empty values
def test_new_set_node_has_no_placeholder_field():
    assert get_default_registry().get_operation("core.set").default_config["fields"] == []


@pytest.mark.parametrize("field,fragment", [
    ({"name": "amount", "value": "", "type": "auto"}, "Field 'amount' has no value"),
    ({"name": "amount", "value": "   ", "type": "number"}, "Field 'amount' has no value"),
    ({"name": "amount", "value": None, "type": "boolean"}, "Field 'amount' has no value"),
    ({"name": "   ", "value": 1}, "Field name must not be blank"),
    ({"name": "a..b", "value": 1}, "has an empty segment"),
])
def test_set_empty_values_and_names_are_rejected_before_run(field, fragment):
    p = plan([trigger(), node("set_1", "core.set", {"fields": [field]})], [edge("e1", "manual_trigger_1", "set_1")])
    messages = [i.message for i in p.errors if i.node_id == "set_1"]
    assert any(fragment in m for m in messages), messages
    # The planner keeps our own wording readable (not lower-cased, no "value error," prefix).
    assert all("value error" not in m.lower() for m in messages)


def test_set_empty_string_is_allowed_when_type_is_string():
    p = plan([trigger(), node("set_1", "core.set", {"fields": [{"name": "note", "value": "", "type": "string"}]})],
             [edge("e1", "manual_trigger_1", "set_1")])
    assert p.valid, [i.message for i in p.errors]


# ---------------------------------------------------------------- (d) conversion errors
@pytest.mark.parametrize("value,type_,fragments", [
    ("abc", "number", ["Field 'amount' expects a number", "the text 'abc'"]),
    ("", "number", ["expects a number", "empty text"]),
    (True, "number", ["the boolean true"]),
    ({"a": 1}, "number", ["an object"]),
    ("maybe", "boolean", ["expects true/false", "the text 'maybe'"]),
    ("{oops", "object", ["expects a JSON object", "not valid JSON"]),
    ({"a": 1}, "array", ["expects a JSON array", "an object"]),
    ("nan", "number", ["expects a number"]),
])
def test_conversion_errors_are_understandable(value, type_, fragments):
    with pytest.raises(NodeExecutionError) as exc:
        coerce(value, type_, "fields[0].value", "amount")
    err = exc.value.error
    for fragment in fragments:
        assert fragment in err.message, err.message
    assert "could not convert string to float" not in err.message
    assert err.field == "fields[0].value" and "change the field type" in err.suggestion
    assert err.details["field_name"] == "amount" and err.details["expected_type"] == type_


@pytest.mark.parametrize("value,type_,expected", [
    ("42", "number", 42), (" 3.5 ", "number", 3.5), (7, "number", 7), ("1e3", "number", 1000.0),
    ("yes", "boolean", True), ("", "boolean", False), ('{"a":1}', "object", {"a": 1}), ([1], "array", [1]),
    (12, "string", "12"), ({"k": 1}, "auto", {"k": 1}),
])
def test_valid_conversions_are_unchanged(value, type_, expected):
    assert coerce(value, type_, "f", "x") == expected


def test_runtime_conversion_error_reaches_execution_detail(app_client: TestClient, auth_headers):
    defn = workflow("bad number", [
        trigger(),
        node("set_1", "core.set", {"fields": [{"name": "amount", "value": "{{trigger.amount}}", "type": "number"}]}),
        node("end_1", "core.end"),
    ], [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "end_1")])
    wf_id = app_client.post("/api/workflows", json={"definition": defn}, headers=auth_headers).json()["id"]
    res = app_client.post(f"/api/workflows/{wf_id}/run?wait=true", json={"input": {"amount": "twelve"}},
                          headers=auth_headers)
    detail = res.json()
    assert detail["status"] == "failed"
    set_run = next(n for n in detail["nodes"] if n["node_id"] == "set_1")
    assert "Field 'amount' expects a number" in set_run["error"]["message"]
    assert "the text 'twelve'" in set_run["error"]["message"]


# ---------------------------------------------------------------- (e) Gemini errors
def _http_error(code, status, message):
    body = json.dumps({"error": {"code": code, "status": status, "message": message}}).encode()
    return urllib.error.HTTPError(f"https://x/models/m:generateContent?key={FAKE_KEY}", code, "err", {},
                                  io.BytesIO(body))


@pytest.mark.parametrize("exc,category,retry_others", [
    (GeminiHTTPError(400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."),
     "invalid_api_key", False),
    (GeminiHTTPError(403, "PERMISSION_DENIED", "denied"), "permission_denied", False),
    (GeminiHTTPError(429, "RESOURCE_EXHAUSTED", "quota"), "quota_exceeded", True),
    (GeminiHTTPError(404, "NOT_FOUND", "models/x is not found"), "model_not_found", True),
    (GeminiHTTPError(503, "UNAVAILABLE", "overloaded"), "provider_unavailable", True),
    (GeminiHTTPError(400, "INVALID_ARGUMENT", "bad field"), "bad_request", True),
    (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), "network", False),
    (urllib.error.URLError(ConnectionRefusedError()), "network", False),
    (TimeoutError("timed out"), "timeout", True),
    (urllib.error.URLError(TimeoutError()), "timeout", True),
    (LLMConfigurationError("GEMINI_API_KEY is not configured."), "missing_api_key", False),
    (ValueError("weird"), "unknown", True),
])
def test_classify_llm_error(exc, category, retry_others):
    info = classify_llm_error(exc, "gemini-x")
    assert info.category == category
    assert info.retry_other_models is retry_others
    assert info.message and info.suggestion and FAKE_KEY not in info.message


def test_http_error_body_is_parsed_and_key_dropped():
    err = GeminiHTTPError.from_http_error(_http_error(400, "INVALID_ARGUMENT", "API key not valid."))
    assert err.status_code == 400 and err.api_status == "INVALID_ARGUMENT"
    assert FAKE_KEY not in str(err)
    assert classify_llm_error(err).category == "invalid_api_key"


def test_scrub_secrets_removes_keys():
    text = f"GET https://g/v1beta/models/m?key={FAKE_KEY}&alt=json failed; raw {FAKE_KEY}; other secret-123"
    cleaned = scrub_secrets(text, ["secret-123"])
    assert FAKE_KEY not in cleaned and "secret-123" not in cleaned and "key=***" in cleaned


def _service(monkeypatch, rest_exc, calls):
    settings = Settings()
    settings.GEMINI_API_KEY = FAKE_KEY
    service = LLMService(settings=settings)

    def fake_rest(model_name, *a, **k):
        calls.append(model_name)
        raise rest_exc

    def no_sdk():
        raise AssertionError("SDK must not be used for this failure class")

    monkeypatch.setattr(service, "_call_rest", fake_rest)
    monkeypatch.setattr(service, "_get_client", no_sdk)
    return service


def test_invalid_key_stops_after_first_model_without_sdk(monkeypatch):
    calls: list = []
    service = _service(monkeypatch, GeminiHTTPError(400, "INVALID_ARGUMENT", "API key not valid."), calls)
    with pytest.raises(LLMGenerationError) as exc:
        service.generate_json("sys", "user")
    assert len(calls) == 1
    assert exc.value.info.category == "invalid_api_key"
    assert "Gemini rejected the API key" in str(exc.value) and FAKE_KEY not in str(exc.value)


def test_missing_model_tries_the_fallback_models(monkeypatch):
    calls: list = []
    service = _service(monkeypatch, GeminiHTTPError(404, "NOT_FOUND", "not found"), calls)
    with pytest.raises(LLMGenerationError) as exc:
        service.generate_json("sys", "user")
    settings = Settings()
    expected = list(dict.fromkeys([settings.GEMINI_MODEL, settings.GEMINI_FALLBACK_MODEL, "gemini-3-flash-preview"]))
    assert calls == expected and len(calls) >= 2  # every distinct candidate tried once, in order
    assert exc.value.info.category == "model_not_found"
    assert f"Gemini model '{calls[0]}' was not found" in str(exc.value)  # primary model reported


def test_network_failure_tries_sdk_then_stops(monkeypatch):
    calls: list = []
    service = _service(monkeypatch, urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")), calls)
    sdk_calls: list = []

    class FakeModels:
        def generate_content(self, **kwargs):
            sdk_calls.append(kwargs["model"])
            raise ConnectionError("network unreachable")

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())
    with pytest.raises(LLMGenerationError) as exc:
        service.generate_review_json("sys", "user")
    assert calls == sdk_calls and len(calls) == 1  # network is down: other models cannot help
    assert exc.value.info.category == "network"


def test_generate_endpoint_returns_structured_secret_free_error(app_client: TestClient, auth_headers):
    from app.api.workflow import get_workflow_generator
    from app.main import app
    from app.services.llm_errors import LLMErrorInfo

    class FailingGenerator:
        def generate(self, prompt, enable_review=True):
            info = LLMErrorInfo("quota_exceeded", "Gemini quota or rate limit exceeded.", "Wait a minute.", True, 429)
            raise LLMGenerationError(f"Gemini quota or rate limit exceeded. key={FAKE_KEY}", info)

    app.dependency_overrides[get_workflow_generator] = lambda: FailingGenerator()
    try:
        res = app_client.post("/api/workflows/generate", json={"prompt": "Build a workflow that fetches data"},
                              headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_workflow_generator, None)
    assert res.status_code == 502
    detail = res.json()["detail"]
    assert detail["category"] == "quota_exceeded" and detail["suggestion"] == "Wait a minute."
    assert FAKE_KEY not in res.text


# ---------------------------------------------------------------- (f) typed JSON values
def test_end_transform_and_http_body_keep_reference_types(app_client: TestClient, auth_headers, http_server):
    defn = workflow("typed", [
        trigger(),
        node("set_1", "core.set", {"fields": [
            {"name": "amount", "value": "{{trigger.amount}}", "type": "number"},
            {"name": "customer", "value": "{{trigger.customer}}"},
            {"name": "tags", "value": "{{trigger.tags}}"},
        ]}),
        node("transform_1", "core.transform", {"mappings": {
            "total": "{{nodes.set_1.output.amount}}",
            "who": "{{nodes.set_1.output.customer}}",
            "labels": "{{nodes.set_1.output.tags}}",
            "summary": "Total {{nodes.set_1.output.amount}} for {{nodes.set_1.output.customer.name}}",
            "literal": {"nested": [1, "{{nodes.set_1.output.amount}}"]},
        }}),
        node("http_1", "http.request", {"method": "POST", "url": f"{http_server}/echo", "body_type": "json",
                                         "body": {"amount": "{{nodes.set_1.output.amount}}",
                                                  "customer": "{{nodes.set_1.output.customer}}",
                                                  "tags": "{{nodes.set_1.output.tags}}"}}),
        node("end_1", "core.end", {"output": {
            "amount": "{{nodes.transform_1.output.total}}",
            "customer": "{{nodes.transform_1.output.who}}",
            "tags": "{{nodes.transform_1.output.labels}}",
            "summary": "{{nodes.transform_1.output.summary}}",
            "nested": "{{nodes.transform_1.output.literal}}",
            "echoed": "{{nodes.http_1.output.body.body}}",
        }}),
    ], [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "transform_1"),
        edge("e3", "transform_1", "http_1"), edge("e4", "http_1", "end_1")])
    wf_id = app_client.post("/api/workflows", json={"definition": defn}, headers=auth_headers).json()["id"]
    res = app_client.post(f"/api/workflows/{wf_id}/run?wait=true", headers=auth_headers, json={"input": {
        "amount": "150", "customer": {"name": "Ada", "tier": 2}, "tags": ["vip", "eu"]}})
    detail = res.json()
    assert detail["status"] == "completed", detail
    out = detail["output"]
    assert out["amount"] == 150 and isinstance(out["amount"], int)
    assert out["customer"] == {"name": "Ada", "tier": 2}
    assert out["tags"] == ["vip", "eu"]
    assert out["summary"] == "Total 150 for Ada"
    assert out["nested"] == {"nested": [1, 150]}
    sent = json.loads(out["echoed"])  # the echo server returns the raw request body text
    assert sent == {"amount": 150, "customer": {"name": "Ada", "tier": 2}, "tags": ["vip", "eu"]}


def test_typed_json_widgets_are_registered():
    reg = get_default_registry()
    widget = {f.key: f.widget for f in reg.get_operation("core.end").ui_fields}
    assert widget["output"] == "json_template"
    assert {f.key: f.widget for f in reg.get_operation("core.transform").ui_fields}["mappings"] == "keyvalue_json"
    assert {f.key: f.widget for f in reg.get_operation("http.request").ui_fields}["body"] == "json_template"
