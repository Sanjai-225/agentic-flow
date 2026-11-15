"""Pre-execution planner tests: unsupported nodes, config, graph, ports, mappings, credentials."""

import copy

from builders import demo_workflow, edge, node, single_node_after_trigger, workflow

from app.engine.planner import plan_workflow
from app.schemas.workflow import WorkflowSchema
from app.services.workflow_upgrade import upgrade_workflow


def plan(defn, **kw):
    return plan_workflow(upgrade_workflow(WorkflowSchema.model_validate(defn)), **kw)


def categories(p):
    return {i.category.value for i in p.errors}


def test_demo_workflow_is_valid_with_stable_order():
    p = plan(demo_workflow("http://localhost"))
    assert p.valid, [i.message for i in p.issues]
    assert p.order == ["trigger", "set_vars", "check_amount", "notify", "end_high", "end_low"]
    assert p.trigger_node_id == "trigger"
    assert p.ancestors["end_high"] == {"trigger", "set_vars", "check_amount", "notify"}


def test_unsupported_and_design_only_nodes_are_rejected():
    defn = workflow("x", [
        node("t", "core.manual_trigger"),
        node("a", "llm_agent"),
        node("b", "unsupported:document_ocr"),
        node("c", "does.not_exist"),
    ], [edge("e1", "t", "a"), edge("e2", "a", "b"), edge("e3", "b", "c")])
    p = plan(defn)
    assert not p.valid
    msgs = {i.node_id: i.message for i in p.errors if i.category.value == "UNSUPPORTED_CAPABILITY"}
    assert "design-only" in msgs["a"]
    assert "document_ocr" in msgs["b"]
    assert "unknown operation" in msgs["c"]


def test_config_schema_errors_point_at_field():
    p = plan(single_node_after_trigger("http.request", {"method": "FETCH"}))
    fields = {i.field for i in p.errors if i.category.value == "SCHEMA_VALIDATION"}
    assert "url" in fields and "method" in fields


def test_unknown_config_keys_are_rejected():
    p = plan(single_node_after_trigger("core.set", {"fields": [], "bogus": 1}))
    assert any(i.field == "bogus" for i in p.errors)


def test_missing_trigger_and_multiple_triggers():
    p = plan(workflow("x", [node("s", "core.set")], []))
    assert any("no trigger" in i.message for i in p.errors)
    p2 = plan(workflow("x", [node("t1", "core.manual_trigger"), node("t2", "core.webhook_trigger"),
                             node("s", "core.set")],
                       [edge("e1", "t1", "s"), edge("e2", "t2", "s")]))
    assert any("Only one trigger" in i.message for i in p2.errors)


def test_if_edges_must_use_true_false_ports():
    defn = demo_workflow("http://x")
    defn["edges"][2]["source_port"] = "main"
    p = plan(defn)
    assert any(i.edge_id == "e3" and "output ports" in i.message for i in p.errors)


def test_end_node_cannot_have_outgoing_edges():
    defn = workflow("x", [node("t", "core.manual_trigger"), node("end", "core.end"), node("s", "core.set")],
                    [edge("e1", "t", "end"), edge("e2", "end", "s")])
    assert any(i.edge_id == "e2" for i in plan(defn).errors)


def test_cycles_are_rejected():
    defn = workflow("x", [node("t", "core.manual_trigger"), node("a", "core.set"), node("b", "core.set"),
                          node("end", "core.end")],
                    [edge("e1", "t", "a"), edge("e2", "a", "b"), edge("e3", "b", "a"), edge("e4", "b", "end")])
    p = plan(defn)
    assert any("cycle" in i.message for i in p.errors)


def test_reference_to_other_branch_is_invalid_mapping():
    defn = copy.deepcopy(demo_workflow("http://x"))
    defn["nodes"][5]["config"] = {"output": "{{nodes.notify.output.status_code}}"}  # end_low uses true-branch node
    p = plan(defn)
    issue = next(i for i in p.errors if i.category.value == "INVALID_MAPPING")
    assert issue.node_id == "end_low" and issue.field == "output"
    assert "does not run before" in issue.message


def test_reference_to_unknown_node_and_bad_syntax():
    p = plan(single_node_after_trigger("core.set", {"fields": [
        {"name": "a", "value": "{{nodes.ghost.output.x}}"},
        {"name": "b", "value": "{{trigger.}}"},
    ]}))
    msgs = [i.message for i in p.errors if i.category.value == "INVALID_MAPPING"]
    assert any("does not exist" in m for m in msgs)
    assert any("Invalid expression" in m for m in msgs)


def test_item_root_only_allowed_in_filter_conditions():
    ok = plan(single_node_after_trigger("core.filter", {
        "items": "{{trigger.list}}",
        "conditions": {"rules": [{"left": "{{item.status}}", "operator": "eq", "right": "a"}]}}))
    assert ok.valid, [i.message for i in ok.errors]
    bad = plan(single_node_after_trigger("core.set", {"fields": [{"name": "a", "value": "{{item.x}}"}]}))
    assert any("only available inside Filter" in i.message for i in bad.errors)


def test_unreachable_node_is_reported():
    defn = workflow("x", [node("t", "core.manual_trigger"), node("a", "core.set"), node("orphan", "core.set")],
                    [edge("e1", "t", "a")])
    p = plan(defn)
    assert any(i.category.value == "GRAPH_VALIDATION" for i in p.errors)


def test_credentials_must_exist_and_be_owned():
    cfg = {"url": "https://example.com", "auth": {"type": "bearer", "credential_id": "cred_other_user"}}
    p = plan(single_node_after_trigger("http.request", cfg), credential_ids={"cred_mine"})
    assert "MISSING_CREDENTIALS" in categories(p)
    p2 = plan(single_node_after_trigger("http.request", {"url": "https://e.com", "auth": {"type": "bearer"}}))
    assert any(i.field == "auth.credential_id" for i in p2.errors)


def test_issues_carry_suggestions():
    p = plan(workflow("x", [node("t", "core.manual_trigger"), node("a", "llm_agent")], [edge("e", "t", "a")]))
    assert all(i.suggestion for i in p.issues)
