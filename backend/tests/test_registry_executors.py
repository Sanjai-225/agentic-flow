"""Registry <-> executor invariants and executable node definitions."""

from fastapi.testclient import TestClient

from app.executors import registered_operations
from app.registry.node_registry import get_default_registry

MILESTONE_1_OPERATIONS = {
    "core.manual_trigger", "core.webhook_trigger", "core.set", "core.json_parse", "core.filter",
    "core.if", "core.transform", "core.end", "http.request",
}
MILESTONE_2_OPERATIONS = {"ai.generate", "ai.agent", "core.form_trigger", "core.schedule_trigger", "core.switch",
                          "core.merge", "core.loop", "core.datetime", "core.array"}
# Operations whose default config intentionally needs user input before it validates.
NEEDS_USER_INPUT = {"core.json_parse", "core.filter", "http.request", "ai.generate", "ai.agent"}


def test_every_executable_definition_has_an_executor_and_vice_versa():
    executable = {d.operation_id for d in get_default_registry().list_executable()}
    assert executable == registered_operations()
    assert executable == MILESTONE_1_OPERATIONS | MILESTONE_2_OPERATIONS


def test_removed_design_only_types_are_not_in_the_active_registry():
    """Milestone 2: design-only types were removed (identifiable via app.registry.legacy, never executable)."""
    reg = get_default_registry()
    for op in ["llm_agent", "switch", "loop", "human_approval", "merge", "wait", "parallel_branch", "join",
               "schedule_trigger", "email_trigger", "code_execution"]:
        assert reg.get_operation(op) is None, op
        resolved = reg.get(op)
        assert resolved is None or (resolved.executable and resolved.operation_id != op), op
    assert all(d.executable and d.status == "ready" for d in reg.list_all())


def test_executable_definitions_are_complete():
    for d in get_default_registry().list_executable():
        assert d.config_model is not None, d.operation_id
        assert d.status == "ready"
        fields = set(d.config_model.model_fields)
        for ui in d.ui_fields:
            assert ui.key.split(".")[0] in fields, f"{d.operation_id}: ui field {ui.key} not in config model"
        # default_config must be a valid config (the editor uses it for new nodes) unless it needs user input
        if d.operation_id not in NEEDS_USER_INPUT:
            d.config_model.model_validate(d.default_config)
        # every example config used by the AI designer must be valid
        d.config_model.model_validate(d.example_config)


def test_legacy_types_resolve_to_executable_operations():
    reg = get_default_registry()
    assert reg.get("condition").operation_id == "core.if"
    assert reg.get("api_call").operation_id == "http.request"
    assert reg.get("set").operation_id == "core.set"
    assert reg.get("core.end").node_type == "end"
    assert reg.get_operation("condition") is None  # strict lookup only accepts operation ids


def test_side_effect_metadata():
    http = get_default_registry().get_operation("http.request")
    assert http.side_effects is True and http.idempotent is False
    assert http.credentials == ["http_bearer", "http_basic", "http_header"]
    assert get_default_registry().get_operation("core.if").ports_out == ["true", "false"]


def test_registry_api_exposes_execution_metadata(app_client: TestClient):
    res = app_client.get("/api/registry/nodes")
    assert res.status_code == 200
    nodes = {n["operation_id"]: n for n in res.json()["nodes"]}
    assert nodes["core.set"]["executable"] is True
    assert nodes["core.set"]["config_schema"]["properties"]["fields"]
    assert "llm_agent" not in nodes and all(n["executable"] for n in nodes.values())
    assert "config_model" not in nodes["core.set"]
    assert app_client.get("/api/registry/nodes/core.if").json()["ports_out"] == ["true", "false"]
