"""Unit tests: calculator parser, built-in tools, provider error classification, provider schema prep."""

import asyncio

import pytest
from pydantic import ValidationError

from app.ai.catalog import get_model, list_models
from app.ai.errors import classify_provider_error, scrub
from app.ai.providers import provider_schema
from app.ai.targets import ModelTarget, model_target_issues
from app.ai.tools import ToolContext, ToolPolicy, get_tool_registry
from app.ai.tools.builtin import ToolInputError
from app.ai.tools.calculator import CalculatorError, evaluate_expression
from app.core.errors import ErrorCategory


@pytest.mark.parametrize("expr,expected", [
    ("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("2 ** 3 ** 2", 512), ("-3 + 5", 2), ("10 // 3", 3), ("10 % 4", 2),
    ("7 / 2", 3.5), ("round(2.345, 2)", 2.35), ("max(1, 9, 4)", 9), ("sum(1, 2, 3.5)", 6.5), ("avg(2, 4)", 3),
    ("sqrt(16)", 4.0), ("abs(-2.5)", 2.5), ("1e3 + 1", 1001.0), ("floor(pi)", 3),
])
def test_calculator_evaluates(expr, expected):
    assert evaluate_expression(expr) == pytest.approx(expected)


@pytest.mark.parametrize("expr,fragment", [
    ("__import__('os')", "Unexpected character"), ("open('x')", "Unexpected character"), ("open(1)", "Unknown name"), ("1/0", "Division by zero"),
    ("2 ** 100000", "too large"), ("(" * 60 + "1" + ")" * 60, "nested too deeply"), ("1 +", "end of expression"),
    ("sqrt(-1)", "undefined"), ("x + 1", "Unknown name"), ("", "empty"), ("9" * 400, "not a finite number"),
    ("[1,2]", "Unexpected character"),
])
def test_calculator_rejects_unsafe_or_invalid_input(expr, fragment):
    with pytest.raises(CalculatorError) as exc:
        evaluate_expression(expr)
    assert fragment in str(exc.value)


def _run(tool_id, **args):
    tool = get_tool_registry().get(tool_id)
    ctx = ToolContext(user_id="u", execution_id="e", node_id="n", cancel_event=asyncio.Event())
    return asyncio.run(tool.execute(tool.input_model.model_validate(args), ctx))


def test_builtin_tools_execute():
    assert _run("datetime", operation="diff", value="2026-01-01T00:00:00Z", other="2026-01-02T12:00:00Z",
                unit="hours")["result"] == 36
    assert _run("datetime", operation="add", value="2026-03-01", amount=-1, unit="days",
                timezone="UTC")["result"].startswith("2026-02-28")
    assert _run("json_tools", operation="parse", text='{"a": [1, 2]}')["result"] == {"a": [1, 2]}
    assert _run("json_tools", operation="get", data={"a": [{"b": 3}]}, path="a.0.b")["result"] == 3
    v = _run("json_tools", operation="validate", data={"a": "x"},
             json_schema={"type": "object", "properties": {"a": {"type": "number"}}})
    assert v["valid"] is False and "a:" in v["errors"][0]
    assert _run("text_tools", operation="word_count", text="one two  three")["result"] == 3
    assert _run("text_tools", operation="replace", text="a-b", find="-", replace_with="+")["result"] == "a+b"
    recs = [{"region": "eu", "v": 2}, {"region": "us", "v": 3}, {"region": "eu", "v": 5}]
    assert _run("data_aggregate", records=recs, operation="sum", field="v") == {"result": 10, "count": 3}
    assert _run("data_aggregate", records=recs, operation="sum_by", field="v", group_by="region")["result"] == \
        {"eu": 7, "us": 3}


@pytest.mark.parametrize("tool_id,args", [
    ("datetime", {"operation": "now", "timezone": "Mars/Base"}),
    ("json_tools", {"operation": "parse", "text": "{bad"}),
    ("data_aggregate", {"records": [{"v": "x"}], "operation": "sum", "field": "v"}),
    ("text_tools", {"operation": "contains", "text": "abc"}),
])
def test_builtin_tools_report_bad_input(tool_id, args):
    with pytest.raises(ToolInputError):
        _run(tool_id, **args)


def test_tool_input_models_forbid_extra_fields():
    tool = get_tool_registry().get("calculator")
    with pytest.raises(ValidationError):
        tool.input_model.model_validate({"expression": "1", "shell": "rm -rf /"})


def test_tool_policy(monkeypatch):
    from app.core.config import get_settings

    registry = get_tool_registry()
    policy = ToolPolicy(["calculator", "http_get"])
    assert policy.denial_reason(registry.get("calculator"), "calculator") is None
    assert "not enabled" in policy.denial_reason(registry.get("datetime"), "datetime")
    assert "Unknown tool" in policy.denial_reason(None, "rm")
    monkeypatch.setattr(get_settings(), "AGENT_DISABLED_TOOLS", ["calculator"])
    assert "disabled on this server" in policy.denial_reason(registry.get("calculator"), "calculator")
    monkeypatch.setattr(get_settings(), "AGENT_ALLOW_NETWORK_TOOLS", False)
    assert "Network tools are disabled" in policy.denial_reason(registry.get("http_get"), "http_get")


def test_every_tool_has_schema_timeout_and_executor():
    for tool in get_tool_registry().list_tools():
        schema = tool.model_schema()
        assert schema["function"]["name"] == tool.id and tool.timeout_seconds > 0 and callable(tool.execute)
        assert tool.side_effects is False  # no side-effecting tool is available by default


class _E(Exception):
    def __init__(self, status=None, msg="err"):
        super().__init__(msg)
        if status is not None:
            self.status_code = status


@pytest.mark.parametrize("exc,category,retry,fallback", [
    (_E(401), ErrorCategory.MODEL_AUTH, False, False),
    (_E(403), ErrorCategory.MODEL_AUTH, False, False),
    (_E(404), ErrorCategory.UNSUPPORTED_MODEL, False, False),
    (_E(429), ErrorCategory.MODEL_UNAVAILABLE, True, True),
    (_E(503), ErrorCategory.MODEL_UNAVAILABLE, True, True),
    (_E(400), ErrorCategory.MODEL_ERROR, False, False),
    (TimeoutError(), ErrorCategory.MODEL_TIMEOUT, True, True),
    (ConnectionError("reset"), ErrorCategory.MODEL_UNAVAILABLE, True, True),
])
def test_provider_error_classification(exc, category, retry, fallback):
    failure = classify_provider_error(exc, "openai", "gpt-6.1-sol")
    assert (failure.category, failure.retryable, failure.fallback_eligible) == (category, retry, fallback)


def test_provider_errors_never_leak_keys():
    exc = _E(401, "Incorrect API key provided: sk-proj-ABCDEFGHIJKLMNOP1234 and AIzaSyABCDEFGHIJKLMNOPQRSTUVWX")
    failure = classify_provider_error(exc, "openai", "m", secrets=["custom-secret-1"])
    assert "sk-proj" not in failure.detail and "AIzaSy" not in failure.detail
    assert scrub("x custom-secret-1 key=abc123", ["custom-secret-1"]) == "x *** key=***"


def test_catalogue_and_capability_validation():
    assert {m.provider for m in list_models()} == {"openai", "anthropic", "gemini"}
    assert get_model("anthropic", "claude-opus-5-5").capabilities.temperature is False
    assert get_model("gemini", "gemini-3.8-flash").capabilities.temperature is True
    assert model_target_issues(ModelTarget(provider="gemini", model="gemini-3.8-flash", temperature=0.2), "m") == []
    issues = model_target_issues(ModelTarget(provider="openai", model="gpt-6.1-sol", reasoning_effort="high",
                                             temperature=0.1), "m")
    assert [i[0] for i in issues] == ["m.temperature"]


def test_provider_schema_preparation_keeps_user_schema_intact():
    user = {"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}}}
    anthropic = provider_schema("anthropic", user)
    assert anthropic["additionalProperties"] is False and anthropic["properties"]["a"]["additionalProperties"] is False
    assert "additionalProperties" not in user and "title" not in user
    assert provider_schema("openai", user)["title"] == "structured_output"


def test_data_aggregate_accepts_json_encoded_records_from_models():
    """Regression (found in live Gemini verification): records sent as JSON strings are decoded strictly."""
    out = _run("data_aggregate", records=['{"id": 1, "amount": 120.5}', '{"id": 2, "amount": 80}'],
               operation="sum", field="amount")
    assert out == {"result": 200.5, "count": 2}
    schema = get_tool_registry().get("data_aggregate").model_schema()["function"]["parameters"]
    assert schema["properties"]["records"]["items"]["anyOf"]  # explicit item types for every provider
    with pytest.raises(ValidationError):
        get_tool_registry().get("data_aggregate").input_model.model_validate(
            {"records": ["not json"], "operation": "sum", "field": "amount"})


def test_transport_errors_with_numeric_codes_are_retryable_not_bad_requests():
    """Regression (found in live verification): aiohttp's TransferEncodingError carries code=400 after a connection
    reset; it must be classified as a retryable, fallback-eligible availability failure - not an HTTP 400."""

    class TransferEncodingError(Exception):
        code = 400

    class ClientPayloadError(Exception):
        pass

    try:
        try:
            raise ConnectionResetError(10054, "forcibly closed")
        except ConnectionResetError as inner:
            raise TransferEncodingError("Not enough data to satisfy transfer length header.") from inner
    except TransferEncodingError as exc:
        wrapped = ClientPayloadError("Response payload is not completed")
        wrapped.__cause__ = exc
        failure = classify_provider_error(wrapped, "gemini", "gemini-3.5-flash")
    assert failure.category == ErrorCategory.MODEL_UNAVAILABLE
    assert failure.retryable and failure.fallback_eligible


def test_env_placeholder_keys_are_treated_as_missing(monkeypatch):
    """backend/.env ships OPENAI_API_KEY / ANTHROPIC_API_KEY placeholders; they must never be sent to a provider."""
    from app.ai.catalog import is_placeholder_key, platform_key
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "your_openai_api_key_here")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "  ")
    assert platform_key("openai") == "" and platform_key("anthropic") == ""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-proj-real-looking-key-123")
    assert platform_key("openai") == "sk-proj-real-looking-key-123"
    assert is_placeholder_key("YOUR_KEY_HERE") and is_placeholder_key("placeholder") and not is_placeholder_key("abc123")


@pytest.mark.parametrize("status,message", [
    (429, "You have no credits remaining. Add credits to continue using the API."),            # OpenAI (live, 2026-11-15)
    (400, "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing."),  # Anthropic
    (429, "insufficient_quota"),
])
def test_billing_errors_are_clear_not_retried_but_can_fall_back(status, message):
    """Regression (found in live verification): a billing failure is not a 'bad request' and not transient."""
    failure = classify_provider_error(_E(status, message), "anthropic", "claude-haiku-5-5")
    assert failure.category == ErrorCategory.MODEL_UNAVAILABLE
    assert "no remaining credit or quota" in failure.message and "billing" in failure.message
    assert failure.retryable is False and failure.fallback_eligible is True
