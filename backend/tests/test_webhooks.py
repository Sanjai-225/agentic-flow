"""Webhook Trigger: secret token, method checks, payload shape and real execution."""

from builders import edge, node, workflow
from conftest import wait_for_execution
from fastapi.testclient import TestClient


def webhook_workflow(method="POST"):
    return workflow("hook", [
        node("hook", "core.webhook_trigger", {"method": method}),
        node("set_1", "core.set", {"fields": [
            {"name": "who", "value": "{{trigger.body.name}}"},
            {"name": "ref", "value": "{{trigger.query.ref}}"},
        ]}),
        node("end", "core.end"),
    ], [edge("e1", "hook", "set_1"), edge("e2", "set_1", "end")])


def setup(client, headers, method="POST"):
    wf_id = client.post("/api/workflows", json={"definition": webhook_workflow(method)}, headers=headers).json()["id"]
    info = client.post(f"/api/workflows/{wf_id}/webhook", headers=headers).json()
    return wf_id, info


def test_webhook_starts_real_execution(app_client: TestClient, auth_headers):
    wf_id, info = setup(app_client, auth_headers)
    assert info["url"].endswith(f"/api/webhooks/{wf_id}/{info['token']}") and info["method"] == "POST"
    res = app_client.post(f"/api/webhooks/{wf_id}/{info['token']}?ref=r-1", json={"name": "Grace"},
                          headers={"Authorization": "Bearer should-not-leak", "X-Source": "crm"})
    assert res.status_code == 202, res.text
    execution = wait_for_execution(app_client, auth_headers, res.json()["execution_id"])
    assert execution["status"] == "completed" and execution["trigger_type"] == "webhook"
    assert execution["output"] == {"who": "Grace", "ref": "r-1"}
    trigger_out = next(n for n in execution["nodes"] if n["node_id"] == "hook")["output"]
    assert trigger_out["method"] == "POST" and trigger_out["headers"]["x-source"] == "crm"
    assert "authorization" not in trigger_out["headers"]


def test_wrong_token_unknown_workflow_and_rotation(app_client: TestClient, auth_headers):
    wf_id, info = setup(app_client, auth_headers)
    assert app_client.post(f"/api/webhooks/{wf_id}/wrong", json={}).status_code == 404
    assert app_client.post(f"/api/webhooks/wf_missing/{info['token']}", json={}).status_code == 404
    rotated = app_client.post(f"/api/workflows/{wf_id}/webhook", headers=auth_headers).json()
    assert app_client.post(f"/api/webhooks/{wf_id}/{info['token']}", json={}).status_code == 404
    assert app_client.post(f"/api/webhooks/{wf_id}/{rotated['token']}", json={"name": "x"}).status_code == 202
    assert app_client.delete(f"/api/workflows/{wf_id}/webhook", headers=auth_headers).status_code == 204
    assert app_client.post(f"/api/webhooks/{wf_id}/{rotated['token']}", json={}).status_code == 404


def test_method_mismatch_and_bad_json(app_client: TestClient, auth_headers):
    wf_id, info = setup(app_client, auth_headers, method="POST")
    assert app_client.get(f"/api/webhooks/{wf_id}/{info['token']}").status_code == 405
    bad = app_client.post(f"/api/webhooks/{wf_id}/{info['token']}", content=b"{oops",
                          headers={"content-type": "application/json"})
    assert bad.status_code == 400


def test_webhook_on_manual_workflow_is_rejected(app_client: TestClient, auth_headers):
    defn = workflow("manual", [node("t", "core.manual_trigger"), node("end", "core.end")], [edge("e", "t", "end")])
    wf_id = app_client.post("/api/workflows", json={"definition": defn}, headers=auth_headers).json()["id"]
    token = app_client.post(f"/api/workflows/{wf_id}/webhook", headers=auth_headers).json()["token"]
    assert app_client.post(f"/api/webhooks/{wf_id}/{token}", json={}).status_code == 409
