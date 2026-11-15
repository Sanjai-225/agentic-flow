"""Switch, Merge, Loop Over Items, Date & Time and Array (Milestone 2, Phase 6).

All runs go through the real API, planner, runner and persistence.
Workflow H = Switch + Merge, Workflow I = Loop Over Items (master prompt section 17).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from builders import edge, node, workflow
from fastapi.testclient import TestClient


def run_wf(client: TestClient, headers, definition, payload=None, expect_valid=True) -> Dict[str, Any]:
    res = client.post("/api/workflows", json={"definition": definition}, headers=headers)
    assert res.status_code == 201, res.text
    wf = res.json()
    if expect_valid:
        assert wf["validation"]["valid"], wf["validation"]["issues"]
    run = client.post(f"/api/workflows/{wf['id']}/run?wait=true", json={"input": payload or {}}, headers=headers)
    assert run.status_code == 200, run.text
    return run.json()


def validate(client, headers, definition) -> List[Dict[str, Any]]:
    return client.post("/api/workflows/validate", json={"definition": definition}, headers=headers).json()["issues"]


def nodes_of(detail) -> Dict[str, Dict[str, Any]]:
    return {n["node_id"]: n for n in detail["nodes"]}


def target_edge(id_, source, target, source_port="main", target_port="main"):
    return {**edge(id_, source, target, source_port), "target_port": target_port}


def rule(left, op, right=None):
    r = {"left": left, "operator": op}
    if right is not None:
        r["right"] = right
    return {"combinator": "all", "rules": [r]}


# =============================================================================================== Workflow H
def workflow_h(require: str = "any", mode: str = "by_input") -> Dict[str, Any]:
    """Manual -> Switch(kind: refund | upgrade | default) -> Set per branch -> Merge(3 inputs) -> End."""
    return workflow("Workflow H", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("switch_1", "core.switch", {"mode": "first", "cases": [
            {"key": "refund", "label": "Refund", "conditions": rule("{{trigger.kind}}", "eq", "refund")},
            {"key": "upgrade", "label": "Upgrade", "conditions": rule("{{trigger.amount}}", "gt", 100)},
        ]}),
        node("set_refund", "core.set", {"fields": [{"name": "lane", "value": "refunds"},
                                                   {"name": "amount", "value": "{{trigger.amount}}", "type": "number"}]}),
        node("set_upgrade", "core.set", {"fields": [{"name": "lane", "value": "sales"}]}),
        node("set_default", "core.set", {"fields": [{"name": "lane", "value": "general"}]}),
        node("merge_1", "core.merge", {"inputs": 3, "mode": mode, "require": require}),
        node("end_1", "core.end", {"output": "{{nodes.merge_1.output}}"}),
    ], [
        edge("e1", "manual_trigger_1", "switch_1"),
        edge("e2", "switch_1", "set_refund", "refund"),
        edge("e3", "switch_1", "set_upgrade", "upgrade"),
        edge("e4", "switch_1", "set_default", "default"),
        target_edge("e5", "set_refund", "merge_1", target_port="input_1"),
        target_edge("e6", "set_upgrade", "merge_1", target_port="input_2"),
        target_edge("e7", "set_default", "merge_1", target_port="input_3"),
        edge("e8", "merge_1", "end_1"),
    ])


@pytest.mark.parametrize("payload,lane,selected,port", [
    ({"kind": "refund", "amount": 30}, "refunds", "refund", "input_1"),
    ({"kind": "other", "amount": 500}, "sales", "upgrade", "input_2"),
    ({"kind": "other", "amount": 5}, "general", "default", "input_3"),
])
def test_workflow_h_switch_routes_every_branch_and_merge_combines(app_client, auth_headers, payload, lane,
                                                                  selected, port):
    detail = run_wf(app_client, auth_headers, workflow_h(), payload)
    assert detail["status"] == "completed", detail
    nodes = nodes_of(detail)
    assert nodes["switch_1"]["route"] == [selected] and nodes["switch_1"]["metadata"]["selected"] == [selected]
    ran = {nid for nid, n in nodes.items() if n["status"] == "success"}
    assert {f"set_{s}" for s in ("refund", "upgrade", "default")} & ran == {f"set_{selected}"}
    assert nodes["merge_1"]["status"] == "success"
    assert detail["output"][port]["lane"] == lane
    assert [k for k, v in detail["output"].items() if v is not None] == [port]
    if selected == "refund":
        assert detail["output"]["input_1"]["amount"] == 30  # typed value preserved through the merge


def test_switch_typed_comparisons_and_all_mode(app_client, auth_headers):
    definition = workflow_h()
    definition["nodes"][1]["config"]["mode"] = "all"
    detail = run_wf(app_client, auth_headers, definition, {"kind": "refund", "amount": "250"})
    nodes = nodes_of(detail)
    # "250" (text) compares numerically with 100, so both cases match in 'all' mode.
    assert nodes["switch_1"]["route"] == ["refund", "upgrade"]
    assert detail["output"]["input_1"]["lane"] == "refunds" and detail["output"]["input_2"]["lane"] == "sales"
    assert detail["output"]["input_3"] is None


def test_merge_require_all_fails_clearly_when_a_branch_was_skipped(app_client, auth_headers):
    detail = run_wf(app_client, auth_headers, workflow_h(require="all"), {"kind": "refund", "amount": 1})
    assert detail["status"] == "failed"
    err = nodes_of(detail)["merge_1"]["error"]
    assert err["category"] == "MISSING_INPUT" and "input_2, input_3" in err["message"]
    assert err["details"]["received"] == ["input_1"]


def test_merge_waits_for_both_parallel_branches_and_runs_once(app_client, auth_headers):
    definition = workflow("fan-in", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("set_a", "core.set", {"fields": [{"name": "a", "value": 1, "type": "number"}]}),
        node("set_b", "core.set", {"fields": [{"name": "b", "value": "{{trigger.b}}"}]}),
        node("merge_1", "core.merge", {"inputs": 2, "mode": "merge_objects", "require": "all"}),
        node("merge_2", "core.merge", {"inputs": 2, "mode": "append", "require": "all"}),
        node("end_1", "core.end", {"output": {"objects": "{{nodes.merge_1.output}}",
                                              "list": "{{nodes.merge_2.output}}"}}),
    ], [edge("e1", "manual_trigger_1", "set_a"), edge("e2", "manual_trigger_1", "set_b"),
        target_edge("e3", "set_a", "merge_1", target_port="input_1"),
        target_edge("e4", "set_b", "merge_1", target_port="input_2"),
        target_edge("e5", "set_a", "merge_2", target_port="input_1"),
        target_edge("e6", "set_b", "merge_2", target_port="input_2"),
        edge("e7", "merge_1", "end_1"), edge("e8", "merge_2", "end_1")])
    detail = run_wf(app_client, auth_headers, definition, {"b": [1, 2]})
    assert detail["status"] == "completed", detail
    out = detail["output"]["end_1"] if "end_1" in detail["output"] else detail["output"]
    assert out["objects"] == {"a": 1, "b": [1, 2]}
    assert out["list"] == {"items": [{"a": 1}, {"b": [1, 2]}], "count": 2}
    assert nodes_of(detail)["merge_1"]["attempts"] == 1


def test_switch_and_merge_validation(app_client, auth_headers):
    bad_port = workflow_h()
    bad_port["edges"][1]["source_port"] = "refnud"
    issues = validate(app_client, auth_headers, bad_port)
    assert any("refnud" in i["message"] and "refund, upgrade, default" in i["message"] for i in issues)
    missing_input = workflow_h()
    missing_input["edges"] = [e for e in missing_input["edges"] if e["id"] != "e7"]
    missing_input["nodes"] = [n for n in missing_input["nodes"] if n["id"] != "set_default"]
    missing_input["edges"] = [e for e in missing_input["edges"] if e["id"] != "e4"]
    issues = validate(app_client, auth_headers, missing_input)
    assert any("Input 'input_3'" in i["message"] and "not connected" in i["message"] for i in issues)
    for cases, fragment in (([{"key": "a", "conditions": rule(1, "eq", 1)}, {"key": "a", "conditions": rule(1, "eq", 1)}],
                             "unique"),
                            ([{"key": "default", "conditions": rule(1, "eq", 1)}], "reserved")):
        bad = workflow_h()
        bad["nodes"][1]["config"]["cases"] = cases
        assert any(fragment in i["message"] for i in validate(app_client, auth_headers, bad))


# =============================================================================================== Workflow I
def workflow_i(body_extra: List[Dict[str, Any]] = None, loop_config: Dict[str, Any] = None,
               body: Dict[str, Any] = None) -> Dict[str, Any]:
    """Manual -> Loop(records) --item--> Transform (body) ; --done--> End(results)."""
    return workflow("Workflow I", [
        node("manual_trigger_1", "core.manual_trigger"),
        node("loop_1", "core.loop", {"items": "{{trigger.records}}", **(loop_config or {})}),
        body or node("transform_1", "core.transform", {"mappings": {
            "name": "{{item.name}}", "total": "{{item.price}}", "position": "{{loop.index}}",
            "label": "Item {{loop.index}} of {{loop.count}}: {{item.name}}"}}),
        *(body_extra or []),
        node("end_1", "core.end", {"output": {"results": "{{nodes.loop_1.output.results}}",
                                              "count": "{{nodes.loop_1.output.count}}"}}),
    ], [edge("e1", "manual_trigger_1", "loop_1"),
        edge("e2", "loop_1", (body or {"id": "transform_1"})["id"], "item"),
        edge("e3", "loop_1", "end_1", "done")])


RECORDS = [{"name": "apple", "price": 1.5}, {"name": "pear", "price": 2}, {"name": "plum", "price": 3}]


def test_workflow_i_loop_runs_body_once_per_item(app_client, auth_headers):
    detail = run_wf(app_client, auth_headers, workflow_i(), {"records": RECORDS})
    assert detail["status"] == "completed", detail
    assert detail["output"]["count"] == 3
    assert detail["output"]["results"] == [
        {"name": "apple", "total": 1.5, "position": 0, "label": "Item 0 of 3: apple"},
        {"name": "pear", "total": 2, "position": 1, "label": "Item 1 of 3: pear"},
        {"name": "plum", "total": 3, "position": 2, "label": "Item 2 of 3: plum"},
    ]
    nodes = nodes_of(detail)
    body = nodes["transform_1"]
    assert body["status"] == "success" and body["metadata"]["iteration_count"] == 3
    assert [i["index"] for i in body["metadata"]["iterations"]] == [0, 1, 2]
    assert nodes["loop_1"]["output"]["succeeded"] == 3 and nodes["loop_1"]["route"] == ["done"]


@pytest.mark.parametrize("records,expected", [([], []), ([{"name": "solo", "price": 9}], [9])])
def test_loop_zero_and_one_item(app_client, auth_headers, records, expected):
    detail = run_wf(app_client, auth_headers, workflow_i(), {"records": records})
    assert detail["status"] == "completed", detail
    assert [r["total"] for r in detail["output"]["results"]] == expected
    body = nodes_of(detail)["transform_1"]
    if not records:
        assert body["status"] == "skipped" and body["metadata"]["skip_reason"] == "The loop had no items."


def test_loop_invalid_input_and_item_limit(app_client, auth_headers):
    detail = run_wf(app_client, auth_headers, workflow_i(), {"records": "not a list"})
    err = nodes_of(detail)["loop_1"]["error"]
    assert detail["status"] == "failed" and "must resolve to an array" in err["message"]
    detail = run_wf(app_client, auth_headers, workflow_i(loop_config={"max_items": 2}), {"records": RECORDS})
    err = nodes_of(detail)["loop_1"]["error"]
    assert err["category"] == "ITERATION_LIMIT" and "3 items" in err["message"]
    assert nodes_of(detail)["transform_1"]["status"] in ("pending", "skipped")


def _typed_body():
    return node("set_1", "core.set", {"fields": [{"name": "price", "value": "{{item.price}}", "type": "number"}]})


def test_loop_item_error_stop_vs_continue(app_client, auth_headers):
    records = [{"price": 1}, {"price": "abc"}, {"price": 3}]
    detail = run_wf(app_client, auth_headers, workflow_i(body=_typed_body()), {"records": records})
    assert detail["status"] == "failed"
    err = nodes_of(detail)["loop_1"]["error"]
    assert "Item 1 failed at node 'set_1'" in err["message"] and "expects a number" in err["message"]
    assert nodes_of(detail)["set_1"]["metadata"]["iteration_count"] == 2  # stopped before item 2

    detail = run_wf(app_client, auth_headers, workflow_i(body=_typed_body(), loop_config={"on_item_error": "continue"}),
                    {"records": records})
    assert detail["status"] == "completed", detail
    assert detail["output"]["results"] == [{"price": 1}, None, {"price": 3}]
    loop = nodes_of(detail)["loop_1"]["output"]
    assert loop["succeeded"] == 2 and loop["failed"] == 1 and loop["errors"][0]["index"] == 1


def test_loop_body_with_branching(app_client, auth_headers):
    """An If inside the body: each item takes its own branch; results come from the branch that ran."""
    definition = workflow_i(body=node("if_1", "core.if", {"conditions": rule("{{item.price}}", "gte", 2)}),
                            body_extra=[node("set_big", "core.set", {"fields": [{"name": "size", "value": "big"}]}),
                                        node("set_small", "core.set", {"fields": [{"name": "size", "value": "small"}]})])
    definition["edges"] += [edge("e4", "if_1", "set_big", "true"), edge("e5", "if_1", "set_small", "false")]
    detail = run_wf(app_client, auth_headers, definition, {"records": RECORDS})
    assert detail["status"] == "completed", detail
    # Only one terminal branch runs per item, so each result is that branch's output.
    assert detail["output"]["results"] == [{"size": "small"}, {"size": "big"}, {"size": "big"}]
    nodes = nodes_of(detail)
    assert nodes["set_big"]["metadata"]["iteration_count"] == 2
    assert nodes["set_small"]["metadata"]["iteration_count"] == 1


def test_loop_validation_rules(app_client, auth_headers):
    # a body node may not feed nodes outside the loop
    leaking = workflow_i()
    leaking["edges"].append(edge("e9", "transform_1", "end_1"))
    issues = validate(app_client, auth_headers, leaking)
    assert any("outside the loop" in i["message"] or "both the 'item' and 'done'" in i["message"] for i in issues)
    # nodes after the loop must not reference per-item body nodes
    bad_ref = workflow_i()
    bad_ref["nodes"][-1]["config"]["output"] = "{{nodes.transform_1.output}}"
    issues = validate(app_client, auth_headers, bad_ref)
    issue = next(i for i in issues if i["node_id"] == "end_1")
    assert "runs once per item" in issue["message"] and "loop_1.output.results" in issue["suggestion"]
    # item / loop roots are only valid inside the body
    outside = workflow_i()
    outside["nodes"][-1]["config"]["output"] = "{{loop.index}}"
    assert any("only available inside a Loop Over Items body" in i["message"]
               for i in validate(app_client, auth_headers, outside))
    # End nodes and nested loops are not allowed in the body
    nested = workflow_i(body=node("loop_2", "core.loop", {"items": "{{item.parts}}"}))
    assert any("nested loops are not supported" in i["message"] for i in validate(app_client, auth_headers, nested))


def test_loop_over_ai_agent_like_body_uses_engine_timeouts(app_client, auth_headers, http_server):
    """Real side-effect-free HTTP call per item: proves body nodes are real executions, not a copied array."""
    body = node("http_1", "http.request", {"method": "GET", "url": f"{http_server}/echo",
                                           "query": {"name": "{{item.name}}"}})
    detail = run_wf(app_client, auth_headers, workflow_i(body=body), {"records": RECORDS})
    assert detail["status"] == "completed", detail
    assert [r["body"]["query"]["name"] for r in detail["output"]["results"]] == ["apple", "pear", "plum"]


# =============================================================================================== Date & Time
@pytest.mark.parametrize("config,expected", [
    ({"operation": "add", "value": "2026-03-28T10:00:00+01:00", "amount": 1, "unit": "days",
      "timezone": "Europe/Berlin"}, "2026-03-29T11:00:00+02:00"),
    ({"operation": "subtract", "value": "2026-01-01T00:00:00Z", "amount": 2, "unit": "hours", "timezone": "UTC"},
     "2025-12-31T22:00:00+00:00"),
    ({"operation": "diff", "value": "2026-01-01", "other": "2026-01-15", "unit": "weeks", "timezone": "UTC"}, 2),
    ({"operation": "format", "value": "2026-07-04T15:30:00Z", "format": "%d/%m/%Y %H:%M",
      "timezone": "America/New_York"}, "04/07/2026 11:30"),
    ({"operation": "start_of", "value": "2026-11-19T15:30:00Z", "start_of": "week", "timezone": "UTC"},
     "2026-11-16T00:00:00+00:00"),
    ({"operation": "start_of", "value": "2026-11-19T15:30:00Z", "start_of": "month", "timezone": "UTC"},
     "2026-11-01T00:00:00+00:00"),
])
def test_datetime_operations(app_client, auth_headers, config, expected):
    definition = workflow("dt", [node("manual_trigger_1", "core.manual_trigger"),
                                 node("datetime_1", "core.datetime", config),
                                 node("end_1", "core.end", {"output": "{{nodes.datetime_1.output.result}}"})],
                          [edge("e1", "manual_trigger_1", "datetime_1"), edge("e2", "datetime_1", "end_1")])
    detail = run_wf(app_client, auth_headers, definition)
    assert detail["status"] == "completed", detail
    assert detail["output"] == expected


def test_datetime_now_parse_and_errors(app_client, auth_headers):
    definition = workflow("dt", [node("manual_trigger_1", "core.manual_trigger"),
                                 node("datetime_1", "core.datetime", {"operation": "parse", "value": "{{trigger.d}}",
                                                                      "timezone": "Asia/Tokyo"}),
                                 node("end_1", "core.end")],
                          [edge("e1", "manual_trigger_1", "datetime_1"), edge("e2", "datetime_1", "end_1")])
    detail = run_wf(app_client, auth_headers, definition, {"d": "2026-11-15T23:00:00Z"})
    out = nodes_of(detail)["datetime_1"]["output"]
    assert out["day"] == 16 and out["weekday"] == "Monday" and out["hour"] == 8
    detail = run_wf(app_client, auth_headers, definition, {"d": "yesterday-ish"})
    assert "not an ISO-8601" in nodes_of(detail)["datetime_1"]["error"]["message"]
    bad_tz = workflow("dt", [node("manual_trigger_1", "core.manual_trigger"),
                             node("datetime_1", "core.datetime", {"operation": "now", "timezone": "Nowhere/Land"})],
                      [edge("e1", "manual_trigger_1", "datetime_1")])
    assert any("Unknown time zone" in i["message"] for i in validate(app_client, auth_headers, bad_tz))


# =============================================================================================== Array
ORDERS = [{"id": 3, "amount": 30, "region": "eu"}, {"id": 1, "amount": 10, "region": "us"},
          {"id": 2, "amount": 20, "region": "eu"}, {"id": 1, "amount": 10, "region": "us"}]


@pytest.mark.parametrize("config,expected", [
    ({"operation": "sum", "field": "amount"}, 70),
    ({"operation": "avg", "field": "amount"}, 17.5),
    ({"operation": "min", "field": "amount"}, 10),
    ({"operation": "max", "field": "amount"}, 30),
    ({"operation": "count"}, 4),
    ({"operation": "pluck", "field": "id"}, [3, 1, 2, 1]),
    ({"operation": "unique", "field": "id"}, [ORDERS[0], ORDERS[1], ORDERS[2]]),
    ({"operation": "sort", "field": "amount", "order": "desc"}, [ORDERS[0], ORDERS[2], ORDERS[1], ORDERS[3]]),
    ({"operation": "limit", "limit": 2}, ORDERS[:2]),
    ({"operation": "chunk", "size": 3}, [ORDERS[:3], ORDERS[3:]]),
    ({"operation": "reverse"}, list(reversed(ORDERS))),
])
def test_array_operations(app_client, auth_headers, config, expected):
    definition = workflow("arr", [node("manual_trigger_1", "core.manual_trigger"),
                                  node("array_1", "core.array", {"items": "{{trigger.orders}}", **config}),
                                  node("end_1", "core.end", {"output": "{{nodes.array_1.output.result}}"})],
                          [edge("e1", "manual_trigger_1", "array_1"), edge("e2", "array_1", "end_1")])
    detail = run_wf(app_client, auth_headers, definition, {"orders": ORDERS})
    assert detail["status"] == "completed", detail
    assert detail["output"] == expected


def test_array_flatten_and_errors(app_client, auth_headers):
    def wf(config):
        return workflow("arr", [node("manual_trigger_1", "core.manual_trigger"),
                                node("array_1", "core.array", {"items": "{{trigger.x}}", **config})],
                        [edge("e1", "manual_trigger_1", "array_1")])
    detail = run_wf(app_client, auth_headers, wf({"operation": "flatten"}), {"x": [[1, 2], 3, [4]]})
    assert nodes_of(detail)["array_1"]["output"]["result"] == [1, 2, 3, 4]
    detail = run_wf(app_client, auth_headers, wf({"operation": "sum", "field": "v"}), {"x": [{"v": 1}, {"v": "x"}]})
    assert "Item 1 field 'v' is not a number" in nodes_of(detail)["array_1"]["error"]["message"]
    detail = run_wf(app_client, auth_headers, wf({"operation": "count"}), {"x": {"not": "array"}})
    assert "must resolve to an array" in nodes_of(detail)["array_1"]["error"]["message"]
    assert any("needs a field" in i["message"] for i in validate(app_client, auth_headers, wf({"operation": "pluck"})))


def test_output_fields_for_flow_nodes(app_client, auth_headers):
    res = app_client.post("/api/workflows/output-fields", json={"definition": workflow_h(mode="append")},
                          headers=auth_headers).json()["nodes"]
    assert [f["path"] for f in res["merge_1"]["fields"]] == [".items", ".items[0]", ".count"]
    loop = app_client.post("/api/workflows/output-fields", json={"definition": workflow_i()},
                           headers=auth_headers).json()["nodes"]["loop_1"]
    assert ".results" in [f["path"] for f in loop["fields"]]


def test_switch_does_not_evaluate_cases_after_the_first_match(app_client, auth_headers):
    """Regression (found in live E2E verification): with mode 'first', a later case referencing a field that this
    payload lacks must not fail the node once an earlier case matched."""
    definition = workflow_h()
    definition["nodes"][2]["config"]["fields"] = [{"name": "lane", "value": "refunds"}]  # branch ignores amount
    detail = run_wf(app_client, auth_headers, definition, {"kind": "refund"})  # no 'amount' at all
    assert detail["status"] == "completed", detail
    assert nodes_of(detail)["switch_1"]["route"] == ["refund"]
    assert [e["case"] for e in nodes_of(detail)["switch_1"]["metadata"]["evaluations"]] == ["refund"]
    # A case that IS evaluated and references a missing field still fails clearly (same rule as If/Else).
    detail = run_wf(app_client, auth_headers, workflow_h(), {"kind": "other"})
    err = nodes_of(detail)["switch_1"]["error"]
    assert err["category"] == "MISSING_INPUT" and "trigger.amount" in err["message"]
    assert err["field"].startswith("cases[1]")
