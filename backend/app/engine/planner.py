"""Pre-execution planner: validates a canonical workflow and computes the run order.

Used by ``POST /api/workflows/validate``, ``POST /api/workflows/{id}/validate``
and before every execution. A workflow with any ``error`` issue never starts.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from pydantic import ValidationError

from app.core.errors import ErrorCategory, NodeExecutionError, ValidationIssue
from app.engine.expressions import iter_expressions, parse_expression
from app.executors import get_executor
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.registry import NodeDefinition
from app.schemas.workflow import CANONICAL_SCHEMA_VERSION, EdgeSchema, WorkflowSchema
from app.services.workflow_upgrade import UNSUPPORTED_PREFIX
from app.validators.graph_validator import GraphValidator


@dataclass
class ExecutionPlan:
    valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    order: List[str] = field(default_factory=list)
    trigger_node_id: Optional[str] = None
    ancestors: Dict[str, Set[str]] = field(default_factory=dict)
    incoming: Dict[str, List[EdgeSchema]] = field(default_factory=dict)
    outgoing: Dict[str, List[EdgeSchema]] = field(default_factory=dict)
    definitions: Dict[str, NodeDefinition] = field(default_factory=dict)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [i.model_dump(mode="json") for i in self.issues],
            "order": self.order,
            "trigger_node_id": self.trigger_node_id,
        }


def _find_credential_ids(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            sub = f"{path}.{k}" if path else k
            if k == "credential_id":
                yield sub, v
            else:
                yield from _find_credential_ids(v, sub)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _find_credential_ids(v, f"{path}[{i}]")


def plan_workflow(
    workflow: WorkflowSchema,
    registry: Optional[NodeRegistry] = None,
    credential_ids: Optional[Set[str]] = None,
) -> ExecutionPlan:
    reg = registry or get_default_registry()
    issues: List[ValidationIssue] = []

    def add(category: ErrorCategory, message: str, *, node_id: Optional[str] = None,
            edge_id: Optional[str] = None, field_: Optional[str] = None, severity: str = "error",
            suggestion: Optional[str] = None) -> None:
        issues.append(ValidationIssue(category=category, message=message, node_id=node_id, edge_id=edge_id,
                                      field=field_, severity=severity, suggestion=suggestion).with_defaults())

    if workflow.schema_version < CANONICAL_SCHEMA_VERSION:
        add(ErrorCategory.SCHEMA_VALIDATION,
            f"Workflow uses schema v{workflow.schema_version}; it must be upgraded to v{CANONICAL_SCHEMA_VERSION}.")

    node_ids = [n.id for n in workflow.nodes]
    index = {nid: i for i, nid in enumerate(node_ids)}
    definitions: Dict[str, NodeDefinition] = {}

    # 1. Operations: registered, executable, config valid.
    for node in workflow.nodes:
        op = node.operation
        label = f"'{node.label}' ({node.id})"
        if not op:
            add(ErrorCategory.UNSUPPORTED_CAPABILITY, f"Node {label} has no operation.", node_id=node.id)
            continue
        if op.startswith(UNSUPPORTED_PREFIX):
            add(ErrorCategory.UNSUPPORTED_CAPABILITY,
                f"Node {label} uses type '{op[len(UNSUPPORTED_PREFIX):]}', which has no executable implementation.",
                node_id=node.id)
            continue
        definition = reg.get_operation(op)
        if definition is None:
            add(ErrorCategory.UNSUPPORTED_CAPABILITY, f"Node {label} uses unknown operation '{op}'.", node_id=node.id)
            continue
        definitions[node.id] = definition
        if not definition.executable or get_executor(op) is None:
            add(ErrorCategory.UNSUPPORTED_CAPABILITY,
                f"Node {label} ('{definition.label}') is design-only and cannot execute yet.", node_id=node.id)
            continue
        if definition.config_model is not None:
            try:
                definition.config_model.model_validate(node.config)
            except ValidationError as exc:
                for err in exc.errors():
                    loc = ".".join(str(p) for p in err["loc"]) or None
                    add(ErrorCategory.SCHEMA_VALIDATION,
                        f"Node {label}: config field '{loc or 'config'}' {err['msg'].lower()}.",
                        node_id=node.id, field_=loc)

    # 2. Generic graph topology checks (existing validator).
    graph = GraphValidator.validate(workflow)
    for message in graph.errors:
        add(ErrorCategory.GRAPH_VALIDATION, message)

    incoming: Dict[str, List[EdgeSchema]] = defaultdict(list)
    outgoing: Dict[str, List[EdgeSchema]] = defaultdict(list)
    for edge in workflow.edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    # 3. Exactly one trigger, with no incoming edges.
    triggers = [nid for nid, d in definitions.items() if d.is_trigger]
    trigger_id: Optional[str] = None
    if not triggers:
        add(ErrorCategory.GRAPH_VALIDATION, "Workflow has no trigger node.",
            suggestion="Add a Manual Trigger or Webhook Trigger as the first node.")
    elif len(triggers) > 1:
        for nid in triggers[1:]:
            add(ErrorCategory.GRAPH_VALIDATION, "Only one trigger node is supported per workflow.", node_id=nid)
        trigger_id = triggers[0]
    else:
        trigger_id = triggers[0]
    for nid in triggers:
        for edge in incoming.get(nid, []):
            add(ErrorCategory.GRAPH_VALIDATION, "Trigger nodes cannot have incoming connections.",
                node_id=nid, edge_id=edge.id)

    # 4. Port validity.
    for edge in workflow.edges:
        src, tgt = definitions.get(edge.source), definitions.get(edge.target)
        if src is not None and edge.source_port not in src.ports_out:
            allowed = ", ".join(src.ports_out) or "none"
            add(ErrorCategory.GRAPH_VALIDATION,
                f"Connection '{edge.id}' leaves '{edge.source}' from port '{edge.source_port}', "
                f"but that node only has output ports: {allowed}.", edge_id=edge.id, node_id=edge.source,
                suggestion="Reconnect the edge from one of the node's output handles.")
        if tgt is not None and not tgt.is_trigger and edge.target_port not in tgt.ports_in:
            add(ErrorCategory.GRAPH_VALIDATION,
                f"Connection '{edge.id}' enters '{edge.target}' on unknown port '{edge.target_port}'.",
                edge_id=edge.id, node_id=edge.target)

    # 5. Cycles and topological order (stable: canonical node order breaks ties).
    indegree = {nid: 0 for nid in node_ids}
    for edge in workflow.edges:
        indegree[edge.target] += 1
    heap = [(index[nid], nid) for nid, deg in indegree.items() if deg == 0]
    heapq.heapify(heap)
    order: List[str] = []
    while heap:
        _, nid = heapq.heappop(heap)
        order.append(nid)
        for edge in outgoing.get(nid, []):
            indegree[edge.target] -= 1
            if indegree[edge.target] == 0:
                heapq.heappush(heap, (index[edge.target], edge.target))
    if len(order) != len(node_ids):
        cyclic = sorted(set(node_ids) - set(order))
        add(ErrorCategory.GRAPH_VALIDATION,
            f"Workflow contains a cycle involving: {', '.join(cyclic)}. Loops are not supported yet.",
            suggestion="Remove the connection that loops back to an earlier node.")

    # 6. Reachability from the trigger.
    ancestors: Dict[str, Set[str]] = {nid: set() for nid in node_ids}
    for nid in order:
        for edge in outgoing.get(nid, []):
            ancestors[edge.target] |= ancestors[nid] | {nid}
    if trigger_id:
        for nid in order:
            if nid != trigger_id and trigger_id not in ancestors[nid]:
                add(ErrorCategory.GRAPH_VALIDATION, f"Node '{nid}' is not reachable from the trigger.", node_id=nid,
                    suggestion="Connect this node to the trigger path or delete it.")

    # 7. Static expression references.
    for node in workflow.nodes:
        definition = definitions.get(node.id)
        lazy = set(definition.lazy_config_fields) if definition else set()
        for source_name, payload in (("config", node.config), ("inputs", node.inputs)):
            for field_path, raw in iter_expressions(payload):
                try:
                    expr = parse_expression(raw, field_path)
                except NodeExecutionError as exc:
                    add(ErrorCategory.INVALID_MAPPING, exc.error.message, node_id=node.id,
                        field_=f"{source_name}.{field_path}" if source_name == "inputs" else field_path)
                    continue
                top = field_path.split(".")[0].split("[")[0]
                if expr.root == "item" and not (source_name == "config" and top in lazy):
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' uses 'item', which is only available inside Filter rules.",
                        node_id=node.id, field_=field_path)
                ref = expr.node_id
                if ref is None:
                    continue
                if ref not in index:
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' references node '{ref}', which does not exist.",
                        node_id=node.id, field_=field_path)
                elif ref not in ancestors.get(node.id, set()):
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' references node '{ref}', which does not run before '{node.id}'.",
                        node_id=node.id, field_=field_path)

    # 8. Credentials.
    for node in workflow.nodes:
        definition = definitions.get(node.id)
        auth = node.config.get("auth") if isinstance(node.config, dict) else None
        if isinstance(auth, dict) and auth.get("type") not in (None, "none") and not auth.get("credential_id"):
            add(ErrorCategory.MISSING_CREDENTIALS, f"Node '{node.id}' requires a credential for "
                f"'{auth.get('type')}' authentication.", node_id=node.id, field_="auth.credential_id")
        if credential_ids is None or definition is None:
            continue
        for field_path, cred in _find_credential_ids(node.config):
            if cred and cred not in credential_ids:
                add(ErrorCategory.MISSING_CREDENTIALS,
                    f"Node '{node.id}' references a credential that does not exist or is not yours.",
                    node_id=node.id, field_=field_path)

    for message in graph.warnings:
        if "cycle" not in message.lower():
            add(ErrorCategory.GRAPH_VALIDATION, message, severity="warning")

    valid = not any(i.severity == "error" for i in issues)
    return ExecutionPlan(
        valid=valid,
        issues=issues,
        order=order,
        trigger_node_id=trigger_id,
        ancestors=ancestors,
        incoming=dict(incoming),
        outgoing=dict(outgoing),
        definitions=definitions,
    )
