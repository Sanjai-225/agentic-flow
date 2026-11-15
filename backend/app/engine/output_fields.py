"""Static output-field inference ("which data fields will this node produce?").

Used by the editor's data picker before a workflow has ever run. Nothing is
executed: fields come from each definition's ``infer_output`` hook (derived
from the node's config, see ``app.registry.output_hooks``) or, failing that,
from the definition's static ``output_schema``. Pass-through nodes (If, End
without an explicit output) inherit the fields of their single predecessor.
Results are hints only; real outputs shown after a run always take precedence.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.registry.node_registry import NodeRegistry, get_default_registry
from app.registry.output_hooks import MAX_DEPTH, PASSTHROUGH_OUTPUT, path_segment
from app.schemas.registry import NodeDefinition
from app.schemas.workflow import WorkflowSchema

MAX_FIELDS_PER_NODE = 60


def paths_from_schema(schema: Dict[str, Any], prefix: str = "", depth: int = 0) -> List[str]:
    """Paths described by a JSON-schema-like ``properties`` tree."""
    out: List[str] = []
    if depth >= MAX_DEPTH or not isinstance(schema, dict):
        return out
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sub in props.items():
            path = prefix + path_segment(str(key))
            out.append(path)
            out.extend(paths_from_schema(sub if isinstance(sub, dict) else {}, path, depth + 1))
    items = schema.get("items")
    if isinstance(items, dict) and items.get("properties"):
        path = f"{prefix}[0]"
        out.append(path)
        out.extend(paths_from_schema(items, path, depth + 1))
    return out


def _dedupe(paths: Iterable[str]) -> List[str]:
    seen: Dict[str, None] = {}
    for p in paths:
        if p and p not in seen:
            seen[p] = None
    return list(seen)[:MAX_FIELDS_PER_NODE]


def _own_paths(definition: NodeDefinition, config: Any) -> Tuple[Any, str]:
    """(paths | PASSTHROUGH_OUTPUT, source) for one node, ignoring the graph."""
    if definition.infer_output is not None:
        try:
            result = definition.infer_output(config if isinstance(config, dict) else {})
        except Exception:  # a half-edited config must never break the editor
            result = None
        if result == PASSTHROUGH_OUTPUT:
            return PASSTHROUGH_OUTPUT, "inherited"
        if result is not None:
            return list(result), "config"
    return paths_from_schema(definition.output_schema), "schema"


def infer_output_fields(workflow: WorkflowSchema,
                        registry: Optional[NodeRegistry] = None) -> Dict[str, Dict[str, Any]]:
    """Return ``{node_id: {"source": str, "fields": [{"path", "expr"}]}}`` for every node.

    ``source`` is ``config``, ``schema``, ``inherited`` or ``unknown``
    (operation missing, unsupported or unregistered).
    """
    reg = registry or get_default_registry()
    by_id = {n.id: n for n in workflow.nodes}
    parents: Dict[str, List[str]] = {}
    for edge in workflow.edges:
        if edge.source in by_id:
            parents.setdefault(edge.target, []).append(edge.source)

    cache: Dict[str, Tuple[List[str], str]] = {}

    def resolve(node_id: str, stack: Tuple[str, ...] = ()) -> Tuple[List[str], str]:
        if node_id in cache:
            return cache[node_id]
        if node_id in stack:  # cycle guard; the planner reports cycles separately
            return [], "unknown"
        node = by_id[node_id]
        definition = reg.get_operation(node.operation) if node.operation else None
        if definition is None:
            result: Tuple[List[str], str] = ([], "unknown")
        else:
            own, source = _own_paths(definition, node.config)
            if own == PASSTHROUGH_OUTPUT:
                preds = parents.get(node_id, [])
                inherited = resolve(preds[0], stack + (node_id,))[0] if len(preds) == 1 else []
                result = (inherited, "inherited")
            else:
                result = (own, source)
        result = (_dedupe(result[0]), result[1])
        cache[node_id] = result
        return result

    out: Dict[str, Dict[str, Any]] = {}
    for node in workflow.nodes:
        paths, source = resolve(node.id)
        out[node.id] = {
            "source": source,
            "fields": [{"path": p, "expr": f"{{{{nodes.{node.id}.output{p}}}}}"} for p in paths],
        }
    return out
