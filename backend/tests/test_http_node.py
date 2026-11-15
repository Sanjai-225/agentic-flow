"""HTTP Request node against a real local server: responses, errors, retries, auth and SSRF."""

import asyncio

import httpx
import pytest
from builders import single_node_after_trigger
from conftest import wait_for_execution
from fastapi.testclient import TestClient

from app.core.errors import ErrorCategory, NodeExecutionError
from app.executors.http import ensure_url_allowed


def run_single(client, headers, config, payload=None, **node_extra):
    defn = single_node_after_trigger("http.request", config, **node_extra)
    res = client.post("/api/workflows", json={"definition": defn}, headers=headers)
    assert res.status_code == 201, res.text
    wf_id = res.json()["id"]
    started = client.post(f"/api/workflows/{wf_id}/run", json={"input": payload or {}}, headers=headers)
    assert started.status_code == 202, started.text
    execution = wait_for_execution(client, headers, started.json()["execution_id"], timeout=20)
    return execution, next(n for n in execution["nodes"] if n["node_id"] == "step")


def test_get_json_with_query_and_headers(app_client: TestClient, auth_headers, http_server):
    execution, step = run_single(app_client, auth_headers, {
        "url": f"{http_server}/echo", "query": {"q": "{{trigger.term}}", "n": 2},
        "headers": {"X-Trace": "abc"}}, {"term": "flows"})
    assert execution["status"] == "completed"
    body = step["output"]["body"]
    assert body["query"] == {"q": "flows", "n": "2"}
    assert body["headers"]["x-trace"] == "abc"
    assert body["headers"]["user-agent"].startswith("AgenticFlow/")


def test_text_response_and_redirect(app_client: TestClient, auth_headers, http_server):
    _, step = run_single(app_client, auth_headers, {"url": f"{http_server}/text"})
    assert step["output"]["body"] == "plain response"
    _, step = run_single(app_client, auth_headers, {"url": f"{http_server}/redirect"})
    assert step["output"]["status_code"] == 200 and step["output"]["url"].endswith("/json")


def test_form_and_raw_bodies(app_client: TestClient, auth_headers, http_server):
    _, step = run_single(app_client, auth_headers, {"method": "PUT", "url": f"{http_server}/echo",
                                                    "body_type": "form", "body": {"a": 1, "b": "x"}})
    assert step["output"]["body"]["body"] == "a=1&b=x"
    _, step = run_single(app_client, auth_headers, {"method": "PATCH", "url": f"{http_server}/echo",
                                                    "body_type": "raw", "body": "hello"})
    assert step["output"]["body"]["body"] == "hello"


@pytest.mark.parametrize("code,category,retryable", [
    (404, "PROVIDER_ERROR", False), (401, "AUTH_FAILURE", False), (429, "RATE_LIMIT", True),
    (500, "PROVIDER_ERROR", True),
])
def test_http_error_statuses_are_categorised(app_client: TestClient, auth_headers, http_server, code, category,
                                             retryable):
    execution, step = run_single(app_client, auth_headers, {"url": f"{http_server}/status/{code}"})
    assert execution["status"] == "failed"
    err = step["error"]
    assert err["category"] == category and err["retryable"] is retryable
    assert err["details"]["status_code"] == code
    assert str(code) in err["message"]


def test_ignore_http_errors_returns_response(app_client: TestClient, auth_headers, http_server):
    execution, step = run_single(app_client, auth_headers, {"url": f"{http_server}/status/404",
                                                            "ignore_http_errors": True})
    assert execution["status"] == "completed" and step["output"]["status_code"] == 404


def test_request_timeout(app_client: TestClient, auth_headers, http_server):
    _, step = run_single(app_client, auth_headers, {"url": f"{http_server}/slow", "timeout_seconds": 0.5})
    assert step["error"]["category"] == "TIMEOUT" and step["error"]["retryable"] is True


def test_node_level_timeout(app_client: TestClient, auth_headers, http_server):
    _, step = run_single(app_client, auth_headers, {"url": f"{http_server}/slow", "timeout_seconds": 30},
                         timeout_seconds=0.5)
    assert step["error"]["category"] == "TIMEOUT" and "0.5s timeout" in step["error"]["message"]


def test_bounded_retry_succeeds_for_safe_method(app_client: TestClient, auth_headers, http_server, call_counts):
    execution, step = run_single(app_client, auth_headers, {"url": f"{http_server}/flaky/retry-ok"},
                                 retry={"max_attempts": 3, "backoff_seconds": 0.01})
    assert execution["status"] == "completed"
    assert step["attempts"] == 3 and step["output"]["body"]["ok"] is True
    assert [e["category"] for e in step["metadata"]["attempt_errors"]] == ["PROVIDER_ERROR", "PROVIDER_ERROR"]
    assert call_counts["retry-ok"] == 3
    assert sum("Retrying" in log["message"] for log in execution["logs"]) == 2


def test_retry_respects_max_attempts(app_client: TestClient, auth_headers, http_server, call_counts):
    execution, step = run_single(app_client, auth_headers, {"url": f"{http_server}/flaky/retry-cap"},
                                 retry={"max_attempts": 2, "backoff_seconds": 0.01})
    assert execution["status"] == "failed" and step["attempts"] == 2
    assert call_counts["retry-cap"] == 2


def test_side_effecting_request_is_never_auto_retried(app_client: TestClient, auth_headers, http_server, call_counts):
    execution, step = run_single(app_client, auth_headers, {"method": "POST", "url": f"{http_server}/count/post-once"},
                                 retry={"max_attempts": 3, "backoff_seconds": 0.01})
    assert execution["status"] == "failed"
    assert call_counts["post-once"] == 1
    assert step["attempts"] == 1
    assert step["metadata"]["retry_blocked"] == "side_effects_without_idempotency"
    assert any("Automatic retry blocked" in log["message"] for log in execution["logs"])


def test_bearer_credential_is_applied_but_never_stored(app_client: TestClient, auth_headers, http_server):
    cred = app_client.post("/api/credentials", json={"type": "http_bearer", "name": "Test API",
                                                     "data": {"token": "s3cret-token"}}, headers=auth_headers)
    assert cred.status_code == 201
    assert "s3cret-token" not in cred.text
    execution, step = run_single(app_client, auth_headers, {
        "url": f"{http_server}/bearer", "auth": {"type": "bearer", "credential_id": cred.json()["id"]}})
    assert execution["status"] == "completed", step["error"]
    assert step["output"]["body"] == {"authorized": True}
    detail = app_client.get(f"/api/executions/{execution['id']}", headers=auth_headers).text
    assert "s3cret-token" not in detail


def test_sensitive_headers_are_redacted_in_recorded_inputs(app_client: TestClient, auth_headers, http_server):
    _, step = run_single(app_client, auth_headers, {"url": f"{http_server}/echo",
                                                    "headers": {"Authorization": "Bearer inline-secret"}})
    assert step["inputs"]["config"]["headers"]["Authorization"] == "***redacted***"


def test_invalid_url_scheme(app_client: TestClient, auth_headers):
    _, step = run_single(app_client, auth_headers, {"url": "file:///etc/passwd"})
    assert step["error"]["category"] == "SCHEMA_VALIDATION" and "scheme" in step["error"]["message"]


@pytest.mark.parametrize("url", ["http://127.0.0.1:8000/x", "http://localhost/x", "http://10.0.0.5/",
                                 "http://169.254.169.254/latest/meta-data", "http://[::1]/"])
def test_ssrf_guard_blocks_private_targets(url):
    with pytest.raises(NodeExecutionError) as exc:
        asyncio.run(ensure_url_allowed(httpx.URL(url), allow_private=False))
    assert exc.value.error.category == ErrorCategory.PERMISSION_DENIED


def test_ssrf_guard_allows_private_when_configured():
    asyncio.run(ensure_url_allowed(httpx.URL("http://127.0.0.1/"), allow_private=True))


@pytest.mark.live
def test_live_public_endpoint(app_client: TestClient, auth_headers):
    """Live: requires outbound internet access."""
    execution, step = run_single(app_client, auth_headers, {"url": "https://httpbin.org/get"})
    assert execution["status"] == "completed" and step["output"]["status_code"] == 200
