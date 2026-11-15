"""Node Registry implementation for managing, discovering, and injecting node knowledge."""

import json
from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.registry.executable_nodes import executable_definitions
from app.schemas.registry import NodeCategory, NodeDefinition


class NodeRegistry:
    """In-memory registry of node definitions keyed by stable operation id.

    Lookups resolve, in order: operation id, node_type, then aliases.
    Registering a definition supersedes any earlier definition whose node_type
    it claims (as node_type or alias).

    The standard registry contains only executable operations (Milestone 2
    removed every design-only type; see ``app.registry.legacy``). New node types
    are added by appending a definition + executor; nothing here is count- or
    type-specific.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeDefinition] = {}
        self._lookup: Dict[str, str] = {}

    @staticmethod
    def _norm(key: str) -> str:
        return key.strip().lower()

    def register(self, definition: NodeDefinition) -> None:
        """Register a node definition (superseding legacy entries it aliases)."""
        claimed = {self._norm(definition.node_type), *(self._norm(a) for a in definition.aliases)}
        for op_id, existing in list(self._nodes.items()):
            if op_id != definition.operation_id and self._norm(existing.node_type) in claimed:
                del self._nodes[op_id]
        self._nodes[definition.operation_id] = definition
        self._rebuild_lookup()

    def _rebuild_lookup(self) -> None:
        lookup: Dict[str, str] = {}
        # Lowest precedence first so higher-precedence keys overwrite.
        for op_id, node in self._nodes.items():
            for alias in node.aliases:
                lookup[self._norm(alias)] = op_id
        for op_id, node in self._nodes.items():
            lookup[self._norm(node.node_type)] = op_id
        for op_id in self._nodes:
            lookup[self._norm(op_id)] = op_id
        self._lookup = lookup

    def get(self, key: str) -> Optional[NodeDefinition]:
        """Look up a definition by operation id, legacy node_type or alias."""
        op_id = self._lookup.get(self._norm(key))
        return self._nodes.get(op_id) if op_id else None

    def get_operation(self, operation_id: str) -> Optional[NodeDefinition]:
        """Strict lookup by operation id only (used by the planner and engine)."""
        return self._nodes.get(operation_id.strip())

    def list_all(self) -> List[NodeDefinition]:
        """Return all registered node definitions."""
        return list(self._nodes.values())

    def list_executable(self) -> List[NodeDefinition]:
        return [n for n in self._nodes.values() if n.executable]

    def list_by_category(self, category: NodeCategory | str) -> List[NodeDefinition]:
        """Return node definitions belonging to a specific category."""
        target = category.value if isinstance(category, NodeCategory) else str(category).lower()
        return [node for node in self._nodes.values() if node.category.value == target]

    def get_categories(self) -> List[str]:
        """Return list of distinct categories currently present in registry."""
        return sorted({node.category.value for node in self._nodes.values()})

    def get_catalog_for_prompt(self) -> str:
        """Token-efficient catalogue of the executable operations for the AI designer/reviewer prompts.

        Generated from the live registry so the designer, reviewer and editor never disagree about
        which operations exist.
        """
        lines = [
            "STANDARD NODE REGISTRY (the ONLY operations available; every one of them executes):",
            "",
        ]
        for node in self.list_executable():
            ports = "/".join(node.ports_out) or "none (terminal)"
            out_fields = ", ".join(node.output_schema.get("properties", {}).keys())
            config_keys = ", ".join(node.config_model.model_fields) if node.config_model else ""
            lines.append(
                f"- operation `{node.operation_id}` (type `{node.node_type}`, {node.label}, "
                f"node ids `{node.id_prefix}_1`, `{node.id_prefix}_2`, ...){' [TRIGGER]' if node.is_trigger else ''}: "
                f"{node.description} | output ports: [{ports}]"
                + (f" | input ports: [{'/'.join(node.ports_in)}]" if node.ports_in not in ([], ["main"]) else "")
                + (f" | output fields: [{out_fields}]" if out_fields else "")
                + (f" | config keys: [{config_keys}]" if config_keys else "")
                + (f"\n    usage: {node.ai_guidance}" if node.ai_guidance else "")
                + f"\n    config example (use exactly this shape): {json.dumps(node.example_config)}"
            )
        lines.append(
            "Condition operators: eq, neq, gt, gte, lt, lte, contains, not_contains, starts_with, ends_with, "
            "is_empty, not_empty, is_true, is_false, regex. Set field types: auto, string, number, boolean, object, array."
        )
        lines.append(
            "\nREGISTRY USAGE RULES:\n"
            "1. Use ONLY the operations listed above. Set both `type` and `operation` to the exact strings shown "
            "(e.g. type \"set_variable\", operation \"core.set\").\n"
            "2. Do NOT invent node types, and do NOT add nodes for services that have no operation above "
            "(email, Slack, databases, file storage, vector search, approvals, waits, custom code). When an "
            "external system must be called, use `http.request` against its HTTP API; otherwise state the "
            "limitation in the workflow description.\n"
            "3. Every workflow has exactly one trigger node (marked [TRIGGER]) with no incoming edges.\n"
            "4. Reference upstream data in config values with {{nodes.<node_id>.output.<field>}}, the trigger "
            "payload with {{trigger.<field>}}, and the previous node's output with {{input.<field>}}.\n"
            "5. An edge's `source_port` must be one of the source node's output ports (\"main\" unless listed "
            "otherwise, e.g. \"true\"/\"false\" for `core.if`)."
        )
        return "\n".join(lines)

    def get_catalog_dict(self) -> Dict[str, Any]:
        """Return full catalog serializable to JSON for API consumers."""
        return {
            "total_nodes": len(self._nodes),
            "categories": self.get_categories(),
            "nodes": [node.model_dump() for node in self._nodes.values()],
        }


def _create_standard_registry() -> NodeRegistry:
    """The active node library: executable operations only."""
    registry = NodeRegistry()
    for definition in executable_definitions():
        registry.register(definition)
    return registry


@lru_cache(maxsize=1)
def get_default_registry() -> NodeRegistry:
    """Return the cached singleton instance of the standard NodeRegistry."""
    return _create_standard_registry()
