"""Acceptance 11: a workflow produced by the AI designer runs on the same engine.

The automated test uses MOCK_DEV_MODE (deterministic designer output). The
``live`` variant exercises the real Gemini designer and requires GEMINI_API_KEY.
"""

import os

import pytest
from conftest import wait_for_execution
from fastapi.testclient import TestClient


def test_designer_output_saves_and_executes(app_client: TestClient, auth_headers, http_server):
    gen = app_client.post("/api/workflows/generate",
                          json={"prompt": "Fetch a URL over http when the amount is large"}, headers=auth_headers)
    assert gen.status_code == 200, gen.text
    designed = gen.json()
    assert designed["execution_readiness"]["executable"] is True, designed["execution_readiness"]

    saved = app_client.post("/api/workflows", json={"definition": designed}, headers=auth_headers)
    assert saved.status_code == 201, saved.text
    wf_id = saved.json()["id"]
    assert saved.json()["validation"]["valid"] is True

    started = app_client.post(f"/api/workflows/{wf_id}/run",
                              json={"input": {"amount": 150, "url": f"{http_server}/json"}}, headers=auth_headers)
    execution = wait_for_execution(app_client, auth_headers, started.json()["execution_id"])
    assert execution["status"] == "completed", execution["error"]
    assert execution["output"]["status"] == 200
    assert execution["output"]["body"]["count"] == 3
    statuses = {n["node_id"]: n["status"] for n in execution["nodes"]}
    assert statuses["end_skipped"] == "skipped" and statuses["http_1"] == "success"


@pytest.mark.live
def test_live_gemini_designer_output_is_validated(app_client: TestClient, auth_headers, monkeypatch):
    """Live: requires GEMINI_API_KEY in the environment (real Gemini call)."""
    key = os.environ.get("LIVE_GEMINI_API_KEY")
    if not key:
        pytest.skip("Set LIVE_GEMINI_API_KEY to run the live designer test.")
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", key)
    monkeypatch.setattr(settings, "MOCK_DEV_MODE", False)
    gen = app_client.post("/api/workflows/generate", json={
        "prompt": "When I run it manually with a name, set a greeting variable, and if the name is 'admin' "
                  "call https://httpbin.org/get, otherwise end.", "review": False}, headers=auth_headers)
    assert gen.status_code == 200, gen.text
    readiness = gen.json()["execution_readiness"]
    # Live output may or may not be fully executable; readiness must be explicit either way.
    assert isinstance(readiness["executable"], bool)
