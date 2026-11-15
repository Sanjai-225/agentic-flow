"""Upgrade v1 (design-only) workflow documents to the canonical v2 schema.

Mapping rules (deterministic, no LLM):
- A node without ``operation`` whose legacy ``type`` resolves through the
  registry gets that definition's ``operation_id``.
- Nodes bound to an external ``tool`` are NOT mapped onto generic executable
  operations (a "trigger" watching Gmail is not a manual trigger); they become
  ``unsupported:<type>`` until an integration provider can run them.
- Node types removed from the library (``app.registry.legacy``) and unknown
  types become ``unsupported:<type>``. They still render and save,
  but the planner rejects them before execution.
- Edges leaving an If node with a legacy ``condition``/``label`` such as
  "true"/"yes" or "false"/"no" get the matching ``source_port``.
"""

from typing import Optional

from app.registry.legacy import LEGACY_NODE_TYPES, UNSUPPORTED_PREFIX
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.workflow import CANONICAL_SCHEMA_VERSION, WorkflowSchema

__all__ = ["UNSUPPORTED_PREFIX", "upgrade_workflow"]

_TRUE_WORDS = {"true", "yes", "y", "pass", "passed", "approved", "match", "matched", "then"}
_FALSE_WORDS = {"false", "no", "n", "else", "otherwise", "fail", "failed", "rejected", "no match"}


def _branch_port(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    word = text.strip().lower()
    if word in _TRUE_WORDS:
        return "true"
    if word in _FALSE_WORDS:
        return "false"
    return None


def upgrade_workflow(workflow: WorkflowSchema, registry: Optional[NodeRegistry] = None) -> WorkflowSchema:
    """Return a v2 copy of ``workflow`` with operations and ports filled in."""
    reg = registry or get_default_registry()
    upgraded = workflow.model_copy(deep=True)

    for node in upgraded.nodes:
        if node.operation:
            continue
        if (node.type or "").strip().lower() in LEGACY_NODE_TYPES:
            # Removed node types are preserved as-is and never remapped to another operation.
            node.operation = f"{UNSUPPORTED_PREFIX}{node.type}"
            continue
        definition = reg.get(node.type)
        if definition is None:
            node.operation = f"{UNSUPPORTED_PREFIX}{node.type}"
        elif definition.executable and node.tool is not None:
            node.operation = f"{UNSUPPORTED_PREFIX}{node.type}"
        else:
            node.operation = definition.operation_id

    if_nodes = {n.id for n in upgraded.nodes if n.operation == "core.if"}
    for edge in upgraded.edges:
        if edge.source in if_nodes and edge.source_port == "main":
            port = _branch_port(edge.condition) or _branch_port(edge.label)
            if port:
                edge.source_port = port

    upgraded.schema_version = CANONICAL_SCHEMA_VERSION
    return upgraded
