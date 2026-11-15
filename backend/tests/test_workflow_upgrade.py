"""v1 -> v2 canonical upgrade tests."""

from app.schemas.workflow import WorkflowSchema
from app.services.mock_workflow_generator import generate_mock_workflow
from app.services.workflow_upgrade import upgrade_workflow


def test_v1_document_still_validates_and_upgrades():
    v1 = {
        "workflow_id": "legacy", "workflow_name": "Legacy",
        "nodes": [
            {"id": "t", "type": "manual_trigger", "label": "Start"},
            {"id": "c", "type": "condition", "label": "Check"},
            {"id": "yes", "type": "end", "label": "Yes"},
            {"id": "no", "type": "document_ocr", "label": "OCR"},
        ],
        "edges": [
            {"id": "e1", "source": "t", "target": "c"},
            {"id": "e2", "source": "c", "target": "yes", "condition": "Yes"},
            {"id": "e3", "source": "c", "target": "no", "label": "otherwise"},
        ],
        "start_nodes": ["t"], "end_nodes": ["yes", "no"],
    }
    wf = upgrade_workflow(WorkflowSchema.model_validate(v1))
    ops = {n.id: n.operation for n in wf.nodes}
    assert ops == {"t": "core.manual_trigger", "c": "core.if", "yes": "core.end", "no": "unsupported:document_ocr"}
    ports = {e.id: e.source_port for e in wf.edges}
    assert ports == {"e1": "main", "e2": "true", "e3": "false"}
    assert wf.schema_version == 2


def test_tool_bound_nodes_are_not_mapped_to_generic_executors():
    """A v1 'trigger' watching Gmail is not a manual trigger: tool-bound nodes stay unsupported."""
    wf = upgrade_workflow(WorkflowSchema.model_validate({
        "workflow_id": "x", "workflow_name": "x",
        "nodes": [{"id": "node_invoice_trigger", "type": "trigger", "label": "Invoice Email Received",
                   "tool": {"name": "Gmail", "operation": "watch_inbox", "status": "not_connected"}},
                  {"id": "manual", "type": "manual_trigger", "label": "Manual",
                   "tool": {"name": "Gmail", "operation": "watch_inbox", "status": "not_connected"}}],
        "edges": [],
    }))
    trigger = next(n for n in wf.nodes if n.id == "node_invoice_trigger")
    assert trigger.tool is not None
    assert trigger.operation == "unsupported:trigger"
    assert next(n for n in wf.nodes if n.id == "manual").operation == "unsupported:manual_trigger"


def test_removed_node_types_are_preserved_never_remapped():
    """Legacy design-only types keep their type, config and edges and are never mapped to new operations."""
    raw = {
        "workflow_id": "legacy", "workflow_name": "Legacy",
        "nodes": [{"id": "t", "type": "manual_trigger", "label": "Start"},
                  {"id": "agent", "type": "llm_agent", "label": "Think", "config": {"model": "x", "prompt": "hi"}},
                  {"id": "sw", "type": "switch", "label": "Route", "config": {"key": "status"}},
                  {"id": "done", "type": "end", "label": "Done"}],
        "edges": [{"id": "e1", "source": "t", "target": "agent"}, {"id": "e2", "source": "agent", "target": "sw"},
                  {"id": "e3", "source": "sw", "target": "done", "label": "ok"}],
    }
    wf = upgrade_workflow(WorkflowSchema.model_validate(raw))
    ops = {n.id: n.operation for n in wf.nodes}
    assert ops == {"t": "core.manual_trigger", "agent": "unsupported:llm_agent", "sw": "unsupported:switch",
                   "done": "core.end"}
    agent = next(n for n in wf.nodes if n.id == "agent")
    assert agent.type == "llm_agent" and agent.config == {"model": "x", "prompt": "hi"}
    assert [(e.source, e.target) for e in wf.edges] == [("t", "agent"), ("agent", "sw"), ("sw", "done")]


def test_existing_operations_are_preserved():
    wf = upgrade_workflow(generate_mock_workflow("fetch a url over http"))
    assert [n.operation for n in wf.nodes][:3] == ["core.manual_trigger", "core.set", "core.if"]


def test_start_and_end_nodes_are_derived_when_omitted():
    wf = WorkflowSchema.model_validate({
        "workflow_id": "x", "workflow_name": "x",
        "nodes": [{"id": "a", "operation": "core.manual_trigger", "label": "a"},
                  {"id": "b", "operation": "core.end", "label": "b"}],
        "edges": [{"id": "e", "source": "a", "target": "b"}],
    })
    assert wf.start_nodes == ["a"] and wf.end_nodes == ["b"]
    assert wf.nodes[0].type == "core.manual_trigger"
