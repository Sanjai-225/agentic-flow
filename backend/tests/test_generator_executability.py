"""AI designer -> executable configs: prompt examples are valid and config errors drive the repair loop."""

import json
from unittest.mock import MagicMock

from app.registry.node_registry import get_default_registry
from app.services.llm_service import build_architect_system_prompt
from app.services.workflow_generator import WorkflowGenerator


def _settings():
    s = MagicMock()
    s.has_gemini_api_key = True
    s.MOCK_DEV_MODE = False
    s.MAX_GENERATION_RETRIES = 2
    s.MAX_REVIEW_CORRECTION_ATTEMPTS = 0
    s.ENABLE_WORKFLOW_REVIEW = False
    return s


def _wf(set_config):
    return json.dumps({
        "workflow_id": "gen", "workflow_name": "Generated",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "operation": "core.manual_trigger", "label": "Start", "config": {}},
            {"id": "s", "type": "set_variable", "operation": "core.set", "label": "Set", "config": set_config},
            {"id": "e", "type": "end", "operation": "core.end", "label": "End", "config": {}},
        ],
        "edges": [{"id": "e1", "source": "t", "target": "s"}, {"id": "e2", "source": "s", "target": "e"}],
        "start_nodes": ["t"], "end_nodes": ["e"],
    })


def test_example_configs_are_valid_and_in_prompt():
    prompt = build_architect_system_prompt()
    for d in get_default_registry().list_executable():
        assert d.example_config, d.operation_id
        d.config_model.model_validate(d.example_config)
        assert json.dumps(d.example_config) in prompt
    assert "output fields: [status_code, headers, body, url, elapsed_ms]" in prompt


def test_config_errors_trigger_repair_and_result_is_executable():
    llm = MagicMock()
    llm.generate_workflow_json.return_value = _wf({"fields": [{"key": "greeting", "value": "hi"}]})
    llm.fix_workflow_json.return_value = _wf({"fields": [{"name": "greeting", "value": "hi"}]})
    result = WorkflowGenerator(llm_service=llm, settings=_settings()).generate("x", enable_review=False)

    errors_sent = llm.fix_workflow_json.call_args.kwargs["validation_errors"]
    assert any("fields.0.name" in e and "Valid config example for core.set" in e for e in errors_sent)
    assert result["execution_readiness"]["executable"] is True


def test_unfixable_configs_return_design_with_honest_readiness():
    llm = MagicMock()
    bad = _wf({"fields": [{"key": "greeting"}]})
    llm.generate_workflow_json.return_value = bad
    llm.fix_workflow_json.return_value = bad
    result = WorkflowGenerator(llm_service=llm, settings=_settings()).generate("x", enable_review=False)
    assert llm.fix_workflow_json.call_count == 2
    assert result["execution_readiness"]["executable"] is False
    assert result["nodes"][1]["operation"] == "core.set"


def test_unsupported_nodes_trigger_bounded_repair_and_are_reported():
    """Milestone 2: the designer must only use registered operations; legacy/invented types are sent back for a
    bounded number of repairs and, if they persist, readiness reports them (never remapped silently)."""
    llm = MagicMock()
    legacy = json.dumps({
        "workflow_id": "gen", "workflow_name": "Design",
        "nodes": [{"id": "t", "type": "manual_trigger", "label": "Start"},
                  {"id": "a", "type": "llm_agent", "label": "Agent"}],
        "edges": [{"id": "e1", "source": "t", "target": "a"}], "start_nodes": ["t"], "end_nodes": ["a"],
    })
    llm.generate_workflow_json.return_value = legacy
    llm.fix_workflow_json.return_value = legacy
    result = WorkflowGenerator(llm_service=llm, settings=_settings()).generate("x", enable_review=False)
    assert llm.fix_workflow_json.call_count == 2  # bounded by MAX_GENERATION_RETRIES
    errors = llm.fix_workflow_json.call_args.kwargs["validation_errors"]
    assert any("UNSUPPORTED_CAPABILITY" in e and "do not invent node types" in e for e in errors)
    assert result["execution_readiness"]["executable"] is False
    assert next(n for n in result["nodes"] if n["id"] == "a")["operation"] == "unsupported:llm_agent"


def test_unsupported_node_repaired_into_registered_operation():
    llm = MagicMock()
    llm.generate_workflow_json.return_value = json.dumps({
        "workflow_id": "gen", "workflow_name": "Design",
        "nodes": [{"id": "t", "type": "manual_trigger", "label": "Start"},
                  {"id": "a", "type": "summarizer", "label": "Summarize"}],
        "edges": [{"id": "e1", "source": "t", "target": "a"}], "start_nodes": ["t"], "end_nodes": ["a"],
    })
    llm.fix_workflow_json.return_value = json.dumps({
        "workflow_id": "gen", "workflow_name": "Design",
        "nodes": [{"id": "t", "type": "manual_trigger", "operation": "core.manual_trigger", "label": "Start"},
                  {"id": "end_1", "type": "end", "operation": "core.end", "label": "Done"}],
        "edges": [{"id": "e1", "source": "t", "target": "end_1"}], "start_nodes": ["t"], "end_nodes": ["end_1"],
    })
    result = WorkflowGenerator(llm_service=llm, settings=_settings()).generate("x", enable_review=False)
    assert llm.fix_workflow_json.call_count == 1
    assert result["execution_readiness"]["executable"] is True
