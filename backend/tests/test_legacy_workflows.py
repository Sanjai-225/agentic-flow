"""Historical workflows containing removed (legacy) node types (Milestone 2, Phase 1).

They must stay loadable and editable, keep their original operation/config/edges,
be clearly identified as unsupported, and never execute or be silently remapped.
"""

from builders import edge, node, workflow
from fastapi.testclient import TestClient


def _legacy_definition():
    return workflow("Legacy design", [
        node("manual_trigger_1", "core.manual_trigger"),
        # A v2 node saved by Milestone 1 with the design-only operation id (operation == node_type).
        node("agent_1", "llm_agent", {"model": "gpt", "prompt": "Summarize {{trigger.text}}"}, "Summarize",
             type="llm_agent"),
        # A v1-upgraded node carrying the unsupported: prefix.
        node("approve_1", "unsupported:human_approval", {"channel": "#ops"}, "Approve", type="human_approval"),
        node("end_1", "core.end"),
    ], [edge("e1", "manual_trigger_1", "agent_1"), edge("e2", "agent_1", "approve_1"),
        edge("e3", "approve_1", "end_1")])


def test_legacy_workflow_saves_reloads_and_is_preserved(app_client: TestClient, auth_headers):
    res = app_client.post("/api/workflows", json={"definition": _legacy_definition()}, headers=auth_headers)
    assert res.status_code == 201, res.text
    wf_id = res.json()["id"]
    reloaded = app_client.get(f"/api/workflows/{wf_id}", headers=auth_headers).json()
    nodes = {n["id"]: n for n in reloaded["definition"]["nodes"]}
    assert nodes["agent_1"]["operation"] == "llm_agent"
    assert nodes["agent_1"]["config"] == {"model": "gpt", "prompt": "Summarize {{trigger.text}}"}
    assert nodes["approve_1"]["operation"] == "unsupported:human_approval"
    assert [(e["source"], e["target"]) for e in reloaded["definition"]["edges"]] == [
        ("manual_trigger_1", "agent_1"), ("agent_1", "approve_1"), ("approve_1", "end_1")]

    validation = reloaded["validation"]
    assert validation["valid"] is False
    by_node = {i["node_id"]: i for i in validation["issues"] if i["node_id"]}
    assert by_node["agent_1"]["category"] == "UNSUPPORTED_CAPABILITY"
    assert "removed from the library" in by_node["agent_1"]["message"]
    assert "AI Agent (ai.agent)" in by_node["agent_1"]["suggestion"]
    assert "configuration and connections are preserved" in by_node["agent_1"]["suggestion"]
    assert "Human-in-the-Loop Approval" in by_node["approve_1"]["message"]


def test_legacy_workflow_never_executes(app_client: TestClient, auth_headers):
    wf_id = app_client.post("/api/workflows", json={"definition": _legacy_definition()},
                            headers=auth_headers).json()["id"]
    res = app_client.post(f"/api/workflows/{wf_id}/run", json={"input": {}}, headers=auth_headers)
    assert res.status_code == 422
    assert app_client.get(f"/api/workflows/{wf_id}/executions", headers=auth_headers).json() == []


def test_legacy_node_can_be_replaced_manually(app_client: TestClient, auth_headers):
    created = app_client.post("/api/workflows", json={"definition": _legacy_definition()},
                              headers=auth_headers).json()
    definition = created["definition"]
    definition["nodes"] = [n for n in definition["nodes"] if n["id"] not in {"agent_1", "approve_1"}]
    definition["nodes"].insert(1, node("set_1", "core.set", {"fields": [{"name": "text", "value": "{{trigger.text}}"}]}))
    definition["edges"] = [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "end_1")]
    res = app_client.put(f"/api/workflows/{created['id']}", json={"definition": definition}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["validation"]["valid"] is True
    run = app_client.post(f"/api/workflows/{created['id']}/run?wait=true", json={"input": {"text": "hi"}},
                          headers=auth_headers)
    assert run.json()["status"] == "completed" and run.json()["output"] == {"text": "hi"}
