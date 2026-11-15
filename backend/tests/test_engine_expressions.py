"""Unit tests for the reference expression resolver."""

import pytest

from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.expressions import ResolutionScope, iter_expressions, parse_expression, resolve_value


def scope(**overrides):
    base = dict(
        node_outputs={"trigger": {"name": "Ada", "amount": 150, "tags": ["a", "b"], "nested": {"k-1": "v"},
                                  "nothing": None},
                      "set_1": {"total": 3.5, "items": [{"id": 1}, {"id": 2}]}},
        node_statuses={"trigger": "success", "set_1": "success", "skipped_node": "skipped", "later": "pending"},
        all_node_ids={"trigger", "set_1", "skipped_node", "later"},
        ancestors={"trigger", "set_1", "skipped_node"},
        trigger_node_id="trigger",
        upstream={"total": 3.5},
        execution={"id": "exe_1"},
        workflow={"id": "wf_1", "version": 2, "name": "WF"},
    )
    base.update(overrides)
    return ResolutionScope(**base)


def test_whole_expression_keeps_native_type():
    assert resolve_value("{{trigger.amount}}", scope()) == 150
    assert resolve_value("  {{ nodes.set_1.output.items }} ", scope()) == [{"id": 1}, {"id": 2}]


def test_embedded_expression_renders_text():
    assert resolve_value("Hi {{trigger.name}}, total={{input.total}}", scope()) == "Hi Ada, total=3.5"
    assert resolve_value("tags={{trigger.tags}}", scope()) == 'tags=["a", "b"]'


def test_paths_indexes_and_quoted_keys():
    assert resolve_value("{{nodes.set_1.output.items[1].id}}", scope()) == 2
    assert resolve_value("{{trigger.tags[-1]}}", scope()) == "b"
    assert resolve_value('{{trigger.nested["k-1"]}}', scope()) == "v"


def test_meta_roots():
    assert resolve_value("{{execution.id}}/{{workflow.version}}", scope()) == "exe_1/2"


def test_recursive_resolution_in_dicts_and_lists():
    value = {"a": ["{{trigger.name}}", {"b": "{{trigger.amount}}"}], "c": 5}
    assert resolve_value(value, scope()) == {"a": ["Ada", {"b": 150}], "c": 5}


def test_default_filter_applies_to_missing_and_null():
    assert resolve_value('{{trigger.missing | default("fallback")}}', scope()) == "fallback"
    assert resolve_value("{{trigger.nothing | default(0)}}", scope()) == 0


def test_null_leaf_without_default_is_allowed():
    assert resolve_value("{{trigger.nothing}}", scope()) is None


def test_missing_path_is_missing_input_with_field():
    with pytest.raises(NodeExecutionError) as exc:
        resolve_value({"url": "{{trigger.missing}}"}, scope())
    assert exc.value.error.category == ErrorCategory.MISSING_INPUT
    assert exc.value.error.field == "url"
    assert "trigger.missing" in exc.value.error.message


def test_null_in_middle_of_path_is_error():
    with pytest.raises(NodeExecutionError) as exc:
        resolve_value("{{trigger.nothing.deeper}}", scope())
    assert exc.value.error.category == ErrorCategory.MISSING_INPUT
    assert "null" in exc.value.error.message


def test_unknown_node_is_invalid_mapping():
    with pytest.raises(NodeExecutionError) as exc:
        resolve_value("{{nodes.ghost.output.x}}", scope())
    assert exc.value.error.category == ErrorCategory.INVALID_MAPPING
    assert "does not exist" in exc.value.error.message


def test_non_ancestor_node_is_invalid_mapping():
    with pytest.raises(NodeExecutionError) as exc:
        resolve_value("{{nodes.later.output.x}}", scope())
    assert exc.value.error.category == ErrorCategory.INVALID_MAPPING
    assert "does not run before" in exc.value.error.message


def test_skipped_node_reference_explains_branch():
    with pytest.raises(NodeExecutionError) as exc:
        resolve_value("{{nodes.skipped_node.output.x}}", scope())
    assert "branch was not taken" in exc.value.error.message


@pytest.mark.parametrize("bad", ["{{}}", "{{foo.bar}}", "{{nodes.x}}", "{{nodes.x.result}}",
                                 "{{trigger.a b}}", "{{trigger[abc]}}", '{{trigger.a | default(nope)}}'])
def test_syntax_errors_are_invalid_mapping(bad):
    with pytest.raises(NodeExecutionError) as exc:
        resolve_value(bad, scope())
    assert exc.value.error.category == ErrorCategory.INVALID_MAPPING


def test_item_root_only_available_with_extra():
    with pytest.raises(NodeExecutionError):
        resolve_value("{{item.id}}", scope())
    assert resolve_value("{{item.id}}", scope(extra={"item": {"id": 9}})) == 9


def test_no_eval_of_python():
    with pytest.raises(NodeExecutionError):
        resolve_value("{{__import__('os').system('echo hi')}}", scope())


def test_iter_expressions_reports_field_paths():
    found = iter_expressions({"a": "{{trigger.x}}", "b": [{"c": "x {{nodes.n.output.y}}"}]})
    assert found == [("a", "trigger.x"), ("b[0].c", "nodes.n.output.y")]
    assert parse_expression("nodes.n.output.y").node_id == "n"
