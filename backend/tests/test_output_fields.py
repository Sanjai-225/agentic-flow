"""Static output-field inference (M1 fix-list item b: show data fields before the first run)."""

from builders import edge, node, workflow
from fastapi.testclient import TestClient

from app.engine.output_fields import infer_output_fields
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.registry.output_hooks import PASSTHROUGH_OUTPUT
from app.schemas.workflow import WorkflowSchema


def infer(nodes, edges, registry=None):
    return infer_output_fields(WorkflowSchema.model_validate(workflow("t", nodes, edges)), registry)


def paths(result, node_id):
    return [f["path"] for f in result[node_id]["fields"]]


TRIGGER = node("manual_trigger_1", "core.manual_trigger", {"sample_payload": {"amount": 5}})


def test_set_fields_nested_and_blank_names_ignored():
    res = infer([TRIGGER, node("set_1", "core.set", {"fields": [
        {"name": "customer", "value": "Ada", "type": "string"},
        {"name": "a.b.c", "value": 1, "type": "number"},
        {"name": "  ", "value": "x"},
        {"name": "odd key", "value": "y"},
    ]})], [edge("e1", "manual_trigger_1", "set_1")])
    assert paths(res, "set_1") == [".customer", ".a", ".a.b", ".a.b.c", '["odd key"]']
    assert res["set_1"]["source"] == "config"
    assert res["set_1"]["fields"][0]["expr"] == "{{nodes.set_1.output.customer}}"
    assert res["set_1"]["fields"][-1]["expr"] == '{{nodes.set_1.output["odd key"]}}'


def test_set_object_value_adds_sub_paths():
    res = infer([TRIGGER, node("set_1", "core.set", {"fields": [{"name": "meta", "value": {"x": 1}}]})],
                [edge("e1", "manual_trigger_1", "set_1")])
    assert paths(res, "set_1") == [".meta", ".meta.x"]


def test_set_keep_input_without_fields_inherits_upstream():
    res = infer([TRIGGER, node("set_1", "core.set", {"fields": [], "keep_input": True})],
                [edge("e1", "manual_trigger_1", "set_1")])
    assert paths(res, "set_1") == [".amount"]
    assert res["set_1"]["source"] == "inherited"


def test_transform_mapping_targets():
    res = infer([TRIGGER, node("transform_1", "core.transform", {"mappings": {
        "total": "{{trigger.amount}}", "customer.name": "Ada"}})],
        [edge("e1", "manual_trigger_1", "transform_1")])
    assert paths(res, "transform_1") == [".total", ".customer", ".customer.name"]


def test_manual_trigger_sample_payload_with_array():
    res = infer([node("manual_trigger_1", "core.manual_trigger", {
        "sample_payload": {"user": {"id": 1}, "items": [{"sku": "a"}]}})], [])
    assert paths(res, "manual_trigger_1") == [".user", ".user.id", ".items", ".items[0]", ".items[0].sku"]
    assert res["manual_trigger_1"]["source"] == "config"


def _if(id_="if_1"):
    return node(id_, "core.if", {"conditions": {"combinator": "all", "rules": [
        {"left": 1, "operator": "eq", "right": 1}]}})


def test_if_inherits_from_single_predecessor():
    res = infer([TRIGGER, node("set_1", "core.set", {"fields": [{"name": "amount", "value": 3}]}), _if()],
                [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "if_1")])
    assert paths(res, "if_1") == paths(res, "set_1") == [".amount"]
    assert res["if_1"]["source"] == "inherited"
    assert res["if_1"]["fields"][0]["expr"] == "{{nodes.if_1.output.amount}}"


def test_end_without_output_inherits_through_if_chain():
    res = infer([TRIGGER, node("set_1", "core.set", {"fields": [{"name": "total", "value": 3}]}), _if(),
                 node("end_1", "core.end", {"output": None})],
                [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "set_1", "if_1"),
                 edge("e3", "if_1", "end_1", "true")])
    assert paths(res, "end_1") == [".total"]
    assert res["end_1"]["source"] == "inherited"


def test_end_with_object_output():
    res = infer([TRIGGER, node("end_1", "core.end", {"output": {"status": "ok", "data": {"n": 1}}})],
                [edge("e1", "manual_trigger_1", "end_1")])
    assert paths(res, "end_1") == [".status", ".data", ".data.n"]
    assert res["end_1"]["source"] == "config"


def test_schema_fallback_for_http():
    res = infer([TRIGGER, node("http_1", "http.request", {"url": "https://example.com"})],
                [edge("e1", "manual_trigger_1", "http_1")])
    assert paths(res, "http_1") == [".status_code", ".headers", ".body", ".url", ".elapsed_ms"]
    assert res["http_1"]["source"] == "schema"


def test_unknown_and_unsupported_operations_are_safe():
    res = infer([TRIGGER, node("legacy_1", "unsupported:llm_agent", {"anything": 1}),
                 node("weird_1", "not.real", {}), _if()],
                [edge("e1", "manual_trigger_1", "legacy_1"), edge("e2", "legacy_1", "if_1"),
                 edge("e3", "manual_trigger_1", "weird_1")])
    assert res["legacy_1"] == {"source": "unknown", "fields": []}
    assert res["weird_1"] == {"source": "unknown", "fields": []}
    assert res["if_1"] == {"source": "inherited", "fields": []}


def test_cycle_does_not_recurse_forever():
    res = infer([_if("if_1"), _if("if_2")], [edge("e1", "if_1", "if_2", "true"), edge("e2", "if_2", "if_1", "true")])
    assert res["if_1"]["fields"] == [] and res["if_2"]["fields"] == []


def test_passthrough_with_multiple_predecessors_is_empty():
    res = infer([TRIGGER, node("set_1", "core.set", {"fields": [{"name": "a", "value": 1}]}),
                 node("set_2", "core.set", {"fields": [{"name": "b", "value": 2}]}),
                 node("end_1", "core.end", {})],
                [edge("e1", "manual_trigger_1", "set_1"), edge("e2", "manual_trigger_1", "set_2"),
                 edge("e3", "set_1", "end_1"), edge("e4", "set_2", "end_1")])
    assert res["end_1"] == {"source": "inherited", "fields": []}


def test_hook_exception_falls_back_to_schema():
    def boom(_config):
        raise RuntimeError("half-edited config")

    registry = NodeRegistry()
    set_def = get_default_registry().get_operation("core.set")
    registry.register(set_def.model_copy(update={"infer_output": boom,
                                                  "output_schema": {"properties": {"fallback": {}}}}))
    res = infer([node("set_1", "core.set", {"fields": [{"name": "a", "value": 1}]})], [], registry)
    assert res["set_1"] == {"source": "schema", "fields": [
        {"path": ".fallback", "expr": "{{nodes.set_1.output.fallback}}"}]}


def test_output_fields_endpoint(app_client: TestClient, auth_headers):
    defn = workflow("t", [TRIGGER, node("set_1", "core.set", {"fields": [{"name": "amount", "value": 1}]})],
                    [edge("e1", "manual_trigger_1", "set_1")])
    res = app_client.post("/api/workflows/output-fields", json={"definition": defn}, headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()["nodes"]
    assert body["set_1"]["fields"] == [{"path": ".amount", "expr": "{{nodes.set_1.output.amount}}"}]
    assert body["manual_trigger_1"]["fields"][0]["path"] == ".amount"
    assert app_client.post("/api/workflows/output-fields", json={"definition": defn}).status_code == 401


def test_registry_ids_and_hooks(app_client: TestClient):
    registry = get_default_registry()
    for definition in registry.list_executable():
        assert definition.id_prefix and definition.id_prefix.replace("_", "").isalnum()
    expected = {"core.manual_trigger": "manual_trigger", "core.set": "set", "core.if": "if", "http.request": "http",
                "core.end": "end", "core.transform": "transform"}
    for op, prefix in expected.items():
        assert registry.get_operation(op).id_prefix == prefix
    assert registry.get_operation("core.if").infer_output({}) == PASSTHROUGH_OUTPUT
    listing = app_client.get("/api/registry/nodes").json()["nodes"]
    set_json = next(n for n in listing if n["operation_id"] == "core.set")
    assert "infer_output" not in set_json and set_json["id_prefix"] == "set"
