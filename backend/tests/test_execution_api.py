"""Milestone 1 acceptance tests through the real API, runner and database.

Acceptance criteria covered (see docs/IMPLEMENTATION_PROGRESS.md):
 1 save/reload  2 manual trigger starts real execution  3 data flows between nodes
 4 Set output   5 If selects branch  6 only selected branch runs  7 HTTP real endpoint
 8 invalid mappings fail clearly  9 unsupported nodes rejected before run  10 history shows real I/O
"""

import asyncio
import copy

from builders import demo_workflow, edge, node, single_node_after_trigger, workflow
from conftest import register, wait_for_execution
from fastapi.testclient import TestClient


def create(client, headers, defn):
    res = client.post("/api/workflows", json={"definition": defn}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def run(client, headers, wf_id, payload=None, expect=202):
    res = client.post(f"/api/workflows/{wf_id}/run", json={"input": payload or {}}, headers=headers)
    assert res.status_code == expect, res.text
    return res.json()


def nodes_by_id(execution):
    return {n["node_id"]: n for n in execution["nodes"]}


# 1 -------------------------------------------------------------------------
def test_manual_workflow_save_and_reload_with_versions(app_client: TestClient, auth_headers):
    defn = demo_workflow("http://127.0.0.1:1")
    defn["nodes"][1]["ui"] = {"position": {"x": 320, "y": 140}}
    created = create(app_client, auth_headers, defn)
    wf_id = created["id"]
    assert created["version"] == 1 and created["definition"]["workflow_id"] == wf_id
    assert created["validation"]["valid"] is True

    reloaded = app_client.get(f"/api/workflows/{wf_id}", headers=auth_headers).json()
    assert reloaded["definition"]["nodes"] == created["definition"]["nodes"]
    assert reloaded["definition"]["nodes"][1]["ui"]["position"] == {"x": 320.0, "y": 140.0}

    edited = copy.deepcopy(reloaded["definition"])
    edited["workflow_name"] = "Renamed"
    edited["nodes"][1]["config"]["fields"].append({"name": "extra", "value": 1, "type": "number"})
    res = app_client.put(f"/api/workflows/{wf_id}", json={"definition": edited}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["version"] == 2
    again = app_client.get(f"/api/workflows/{wf_id}", headers=auth_headers).json()
    assert again["name"] == "Renamed" and again["definition"]["version"] == 2
    assert len(again["definition"]["nodes"][1]["config"]["fields"]) == 4

    listing = app_client.get("/api/workflows", headers=auth_headers).json()
    assert any(w["id"] == wf_id and w["version"] == 2 for w in listing)


def test_invalid_definition_is_rejected_with_field_errors(app_client: TestClient, auth_headers):
    res = app_client.post("/api/workflows", json={"definition": {"workflow_name": "x", "nodes": []}},
                          headers=auth_headers)
    assert res.status_code == 422
    assert res.json()["detail"]["errors"][0]["field"] == "nodes"


# 2-7, 10 ------------------------------------------------------------------
def test_demo_workflow_true_branch_runs_http_against_real_server(app_client: TestClient, auth_headers, http_server):
    wf_id = create(app_client, auth_headers, demo_workflow(http_server))["id"]
    started = run(app_client, auth_headers, wf_id, {"name": "Ada", "amount": 150})
    assert started["status"] == "pending" and started["execution_id"].startswith("exe_")

    execution = wait_for_execution(app_client, auth_headers, started["execution_id"])
    assert execution["status"] == "completed", execution["error"]
    nodes = nodes_by_id(execution)

    # 2: real backend execution with real timestamps
    assert execution["trigger_type"] == "manual" and execution["started_at"] and execution["finished_at"]
    assert nodes["trigger"]["status"] == "success"
    assert nodes["trigger"]["output"] == {"name": "Ada", "amount": 150}

    # 3 + 4: data reaches the next node; Set output is exact
    assert nodes["set_vars"]["output"] == {"customer": "Ada", "amount": 150, "greeting": "Hello Ada!"}
    assert nodes["set_vars"]["inputs"]["upstream"] == {"name": "Ada", "amount": 150}

    # 5: If picks the true branch
    assert nodes["check_amount"]["route"] == ["true"]
    assert nodes["check_amount"]["metadata"]["result"] is True

    # 6: only the selected branch runs
    assert nodes["notify"]["status"] == "success"
    assert nodes["end_high"]["status"] == "success"
    assert nodes["end_low"]["status"] == "skipped"
    assert nodes["end_low"]["output"] is None

    # 7: the HTTP node really called the server and stored its response
    http_out = nodes["notify"]["output"]
    assert http_out["status_code"] == 200
    echoed = http_out["body"]
    assert echoed["method"] == "POST"
    assert echoed["query"] == {"source": "agentic-flow"}
    assert echoed["headers"]["x-customer"] == "Ada"
    assert '"greeting": "Hello Ada!"' in echoed["body"] or '"greeting":"Hello Ada!"' in echoed["body"]

    # final workflow output = End node output
    assert execution["output"]["branch"] == "high" and execution["output"]["status"] == 200

    # 10: inspector data: resolved inputs, logs, durations
    assert nodes["notify"]["inputs"]["config"]["url"] == f"{http_server}/echo"
    assert nodes["notify"]["duration_ms"] > 0
    assert any(log["node_id"] == "notify" and "POST" in log["message"] for log in execution["logs"])
    assert execution["workflow_definition"]["workflow_id"] == wf_id


def test_demo_workflow_false_branch_skips_http(app_client: TestClient, auth_headers, http_server):
    wf_id = create(app_client, auth_headers, demo_workflow(http_server))["id"]
    execution = wait_for_execution(app_client, auth_headers,
                                   run(app_client, auth_headers, wf_id, {"name": "Bo", "amount": 20})["execution_id"])
    assert execution["status"] == "completed"
    nodes = nodes_by_id(execution)
    assert nodes["check_amount"]["route"] == ["false"]
    assert nodes["notify"]["status"] == "skipped" and nodes["end_high"]["status"] == "skipped"
    assert nodes["end_low"]["status"] == "success"
    # {{input.amount}} on the false branch sees the If node's pass-through data
    assert execution["output"] == {"branch": "low", "amount": 20}


def test_run_with_wait_returns_final_detail(app_client: TestClient, auth_headers, http_server):
    wf_id = create(app_client, auth_headers, demo_workflow(http_server))["id"]
    res = app_client.post(f"/api/workflows/{wf_id}/run?wait=true", json={"input": {"name": "C", "amount": 1}},
                          headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "completed"


# 8 -------------------------------------------------------------------------
def test_missing_reference_fails_node_with_understandable_error(app_client: TestClient, auth_headers):
    defn = workflow("bad mapping", [
        node("trigger", "core.manual_trigger"),
        node("set_1", "core.set", {"fields": [{"name": "email", "value": "{{trigger.customer.email}}"}]}, "Set Email"),
        node("end", "core.end"),
    ], [edge("e1", "trigger", "set_1"), edge("e2", "set_1", "end")])
    wf_id = create(app_client, auth_headers, defn)["id"]
    execution = wait_for_execution(app_client, auth_headers,
                                   run(app_client, auth_headers, wf_id, {"name": "no customer"})["execution_id"])
    assert execution["status"] == "failed"
    failed = nodes_by_id(execution)["set_1"]
    assert failed["status"] == "failed"
    err = failed["error"]
    assert err["category"] == "MISSING_INPUT"
    assert err["field"] == "fields[0].value"
    assert "trigger.customer" in err["message"]
    assert err["suggestion"] and err["node_id"] == "set_1" and err["operation"] == "core.set"
    assert err["details"]["correlation_id"] == execution["correlation_id"]
    assert nodes_by_id(execution)["end"]["status"] == "skipped"
    assert execution["error"]["node_id"] == "set_1"


def test_invalid_static_mapping_is_rejected_before_execution(app_client: TestClient, auth_headers):
    defn = demo_workflow("http://127.0.0.1:1")
    defn["nodes"][5]["config"] = {"output": "{{nodes.notify.output.body}}"}
    created = create(app_client, auth_headers, defn)
    assert created["validation"]["valid"] is False
    res = app_client.post(f"/api/workflows/{created['id']}/run", json={"input": {}}, headers=auth_headers)
    assert res.status_code == 422
    issue = res.json()["detail"]["issues"][0]
    assert issue["category"] == "INVALID_MAPPING" and issue["node_id"] == "end_low"
    assert app_client.get(f"/api/workflows/{created['id']}/executions", headers=auth_headers).json() == []


# 9 -------------------------------------------------------------------------
def test_unsupported_nodes_are_rejected_before_execution(app_client: TestClient, auth_headers):
    defn = workflow("has agent", [
        node("trigger", "core.manual_trigger"),
        node("agent", "llm_agent", {"model": "x"}, "Research Agent"),
        node("end", "core.end"),
    ], [edge("e1", "trigger", "agent"), edge("e2", "agent", "end")])
    created = create(app_client, auth_headers, defn)  # saving design-only nodes is allowed
    assert created["validation"]["valid"] is False
    res = app_client.post(f"/api/workflows/{created['id']}/run", json={}, headers=auth_headers)
    assert res.status_code == 422
    issue = res.json()["detail"]["issues"][0]
    assert issue["category"] == "UNSUPPORTED_CAPABILITY" and issue["node_id"] == "agent"
    assert app_client.get(f"/api/workflows/{created['id']}/executions", headers=auth_headers).json() == []

    v = app_client.post("/api/workflows/validate", json={"definition": defn}, headers=auth_headers).json()
    assert v["valid"] is False and v["issues"][0]["node_id"] == "agent"


# 10 ------------------------------------------------------------------------
def test_execution_history_lists_real_runs(app_client: TestClient, auth_headers, http_server):
    wf_id = create(app_client, auth_headers, demo_workflow(http_server))["id"]
    ids = [run(app_client, auth_headers, wf_id, {"name": "A", "amount": amt})["execution_id"] for amt in (500, 5)]
    for i in ids:
        wait_for_execution(app_client, auth_headers, i)
    history = app_client.get(f"/api/workflows/{wf_id}/executions", headers=auth_headers).json()
    assert {h["id"] for h in history} == set(ids)
    assert all(h["status"] == "completed" and h["duration_ms"] is not None for h in history)
    summaries = app_client.get("/api/workflows", headers=auth_headers).json()
    assert next(w for w in summaries if w["id"] == wf_id)["last_execution_status"] == "completed"


# Data nodes ------------------------------------------------------------------
def test_json_parse_filter_transform_chain(app_client: TestClient, auth_headers, http_server):
    defn = workflow("data chain", [
        node("trigger", "core.manual_trigger"),
        node("fetch", "http.request", {"url": f"{http_server}/json", "response_format": "text"}),
        node("parse", "core.json_parse", {"source": "{{nodes.fetch.output.body}}"}),
        node("active", "core.filter", {"items": "{{nodes.parse.output.items}}", "conditions": {
            "combinator": "all", "rules": [{"left": "{{item.status}}", "operator": "eq", "right": "active"}]}}),
        node("shape", "core.transform", {"mappings": {"summary.kept": "{{nodes.active.output.kept}}",
                                                      "summary.ids": "{{nodes.active.output.items}}",
                                                      "source": "{{trigger.source | default(\"api\")}}"}}),
        node("end", "core.end"),
    ], [edge("e1", "trigger", "fetch"), edge("e2", "fetch", "parse"), edge("e3", "parse", "active"),
        edge("e4", "active", "shape"), edge("e5", "shape", "end")])
    wf_id = create(app_client, auth_headers, defn)["id"]
    execution = wait_for_execution(app_client, auth_headers, run(app_client, auth_headers, wf_id)["execution_id"])
    assert execution["status"] == "completed", execution["error"]
    nodes = nodes_by_id(execution)
    assert isinstance(nodes["fetch"]["output"]["body"], str)
    assert nodes["parse"]["output"]["count"] == 3
    assert nodes["active"]["output"]["kept"] == 2 and nodes["active"]["output"]["dropped"] == 1
    assert execution["output"] == {"summary": {"kept": 2, "ids": [{"id": 1, "status": "active"},
                                                                  {"id": 3, "status": "active"}]},
                                   "source": "api"}


def test_json_parse_invalid_text_fails_clearly(app_client: TestClient, auth_headers):
    wf_id = create(app_client, auth_headers,
                   single_node_after_trigger("core.json_parse", {"source": "{{trigger.raw}}"}))["id"]
    execution = wait_for_execution(app_client, auth_headers,
                                   run(app_client, auth_headers, wf_id, {"raw": "{not json"})["execution_id"])
    err = nodes_by_id(execution)["step"]["error"]
    assert err["category"] == "NODE_EXECUTION" and "not valid JSON" in err["message"] and err["field"] == "source"


def test_on_error_continue_passes_error_downstream(app_client: TestClient, auth_headers):
    defn = workflow("continue", [
        node("trigger", "core.manual_trigger"),
        node("parse", "core.json_parse", {"source": "nope"}, on_error="continue"),
        node("end", "core.end", {"output": "{{nodes.parse.output.error.category}}"}),
    ], [edge("e1", "trigger", "parse"), edge("e2", "parse", "end")])
    wf_id = create(app_client, auth_headers, defn)["id"]
    execution = wait_for_execution(app_client, auth_headers, run(app_client, auth_headers, wf_id)["execution_id"])
    assert execution["status"] == "completed"
    assert nodes_by_id(execution)["parse"]["status"] == "failed"
    assert execution["output"] == "NODE_EXECUTION"


# Isolation / cancellation / restart ------------------------------------------
def test_users_cannot_access_each_others_workflows_or_executions(app_client: TestClient, auth_headers, http_server):
    wf_id = create(app_client, auth_headers, demo_workflow(http_server))["id"]
    exec_id = run(app_client, auth_headers, wf_id, {"name": "A", "amount": 1})["execution_id"]
    wait_for_execution(app_client, auth_headers, exec_id)

    other = register(app_client)
    assert app_client.get(f"/api/workflows/{wf_id}", headers=other).status_code == 404
    assert app_client.put(f"/api/workflows/{wf_id}", json={"definition": demo_workflow("http://x")},
                          headers=other).status_code == 404
    assert app_client.post(f"/api/workflows/{wf_id}/run", json={}, headers=other).status_code == 404
    assert app_client.get(f"/api/workflows/{wf_id}/executions", headers=other).status_code == 404
    assert app_client.get(f"/api/executions/{exec_id}", headers=other).status_code == 404
    assert app_client.post(f"/api/executions/{exec_id}/cancel", headers=other).status_code == 404
    assert app_client.delete(f"/api/workflows/{wf_id}", headers=other).status_code == 404
    assert wf_id not in {w["id"] for w in app_client.get("/api/workflows", headers=other).json()}


def test_running_execution_can_be_cancelled(app_client: TestClient, auth_headers, http_server):
    wf_id = create(app_client, auth_headers, single_node_after_trigger(
        "http.request", {"url": f"{http_server}/slow", "timeout_seconds": 30}))["id"]
    exec_id = run(app_client, auth_headers, wf_id)["execution_id"]
    for _ in range(100):
        detail = app_client.get(f"/api/executions/{exec_id}", headers=auth_headers).json()
        if nodes_by_id(detail).get("step", {}).get("status") == "running":
            break
        asyncio.run(asyncio.sleep(0.02))
    res = app_client.post(f"/api/executions/{exec_id}/cancel", headers=auth_headers)
    assert res.status_code == 200 and res.json()["status"] in {"cancelling", "cancelled"}
    final = wait_for_execution(app_client, auth_headers, exec_id, timeout=10)
    assert final["status"] == "cancelled"
    assert final["error"]["category"] == "CANCELLED"
    assert app_client.post(f"/api/executions/{exec_id}/cancel", headers=auth_headers).status_code == 409


def test_interrupted_executions_are_reconciled_on_startup(app_client: TestClient, auth_headers, http_server):
    from app.db.models import Execution
    from app.db.session import get_sessionmaker
    from app.engine.worker import ExecutionManager

    wf_id = create(app_client, auth_headers, demo_workflow(http_server))["id"]
    me = app_client.get("/api/auth/me", headers=auth_headers).json()

    async def scenario():
        sm = get_sessionmaker()
        async with sm() as s:
            stale = Execution(workflow_id=wf_id, workflow_version=1, user_id=me["id"], status="running",
                              trigger_type="manual", correlation_id="c")
            s.add(stale)
            await s.commit()
            stale_id = stale.id
        count = await ExecutionManager(sm).reconcile_interrupted()
        return stale_id, count

    stale_id, count = app_client.portal.call(scenario)
    assert count >= 1
    detail = app_client.get(f"/api/executions/{stale_id}", headers=auth_headers).json()
    assert detail["status"] == "failed"
    assert "interrupted" in detail["error"]["message"]
