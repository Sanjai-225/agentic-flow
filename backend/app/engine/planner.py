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
from app.engine.expressions import iter_expressions, parse_expression, unknown_node_suggestion
from app.executors import get_executor
from app.registry.legacy import legacy_message, legacy_type_of
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
    # Loop Over Items: loop node id -> body node ids (topological order); body node id -> owning loop id.
    loop_bodies: Dict[str, List[str]] = field(default_factory=dict)
    body_owner: Dict[str, str] = field(default_factory=dict)

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
        legacy = legacy_type_of(op, node.type)
        definition = None if op.startswith(UNSUPPORTED_PREFIX) else reg.get_operation(op)
        if definition is None and legacy:
            # A node type removed from the library (Milestone 2). Kept as-is, never remapped.
            message, suggestion = legacy_message(label, legacy)
            add(ErrorCategory.UNSUPPORTED_CAPABILITY, message, node_id=node.id, suggestion=suggestion)
            continue
        if op.startswith(UNSUPPORTED_PREFIX):
            add(ErrorCategory.UNSUPPORTED_CAPABILITY,
                f"Node {label} uses type '{op[len(UNSUPPORTED_PREFIX):]}', which has no executable implementation.",
                node_id=node.id,
                suggestion="Replace it with an operation from the node library; its stored configuration and "
                           "connections are kept so you can copy what you need.")
            continue
        if definition is None:
            add(ErrorCategory.UNSUPPORTED_CAPABILITY, f"Node {label} uses unknown operation '{op}'.", node_id=node.id,
                suggestion="Replace it with an operation from the node library.")
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
                    if err.get("type") == "value_error":
                        # Our own validator messages are written for users; keep them verbatim.
                        detail = str(err["msg"]).removeprefix("Value error, ").rstrip(".")
                        message = f"Node {label}: {detail} (config field '{loc or 'config'}')."
                    else:
                        message = f"Node {label}: config field '{loc or 'config'}' {err['msg'].lower()}."
                    add(ErrorCategory.SCHEMA_VALIDATION, message, node_id=node.id, field_=loc)

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

    # 4. Port validity (ports may be derived from the node config, e.g. Switch cases, Merge inputs).
    node_by_id = {n.id: n for n in workflow.nodes}
    ports: Dict[str, tuple[List[str], List[str]]] = {
        nid: d.ports_for(node_by_id[nid].config) for nid, d in definitions.items()}
    for edge in workflow.edges:
        src, tgt = definitions.get(edge.source), definitions.get(edge.target)
        src_out = ports[edge.source][1] if src is not None else []
        tgt_in = ports[edge.target][0] if tgt is not None else []
        if src is not None and edge.source_port not in src_out:
            allowed = ", ".join(src_out) or "none"
            add(ErrorCategory.GRAPH_VALIDATION,
                f"Connection '{edge.id}' leaves '{edge.source}' from port '{edge.source_port}', "
                f"but that node only has output ports: {allowed}.", edge_id=edge.id, node_id=edge.source,
                suggestion="Reconnect the edge from one of the node's output handles.")
        if tgt is not None and not tgt.is_trigger and edge.target_port not in tgt_in:
            add(ErrorCategory.GRAPH_VALIDATION,
                f"Connection '{edge.id}' enters '{edge.target}' on unknown port '{edge.target_port}'. "
                f"Input ports: {', '.join(tgt_in) or 'none'}.",
                edge_id=edge.id, node_id=edge.target)
    for nid, definition in definitions.items():
        spec = definition.dynamic_ports
        if spec is not None and spec.direction == "in":
            connected = {e.target_port for e in incoming.get(nid, [])}
            for port in ports[nid][0]:
                if port not in connected:
                    add(ErrorCategory.GRAPH_VALIDATION,
                        f"Input '{port}' of '{node_by_id[nid].label}' ({nid}) is not connected.", node_id=nid,
                        suggestion="Connect a branch to every input, or reduce the number of inputs.")

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

    # 6b. Loop Over Items bodies: nodes reachable from a loop's 'item' port run once per item.
    loop_bodies: Dict[str, List[str]] = {}
    body_owner: Dict[str, str] = {}
    position = {nid: i for i, nid in enumerate(order)}
    for loop_id in [nid for nid in order if definitions.get(nid) and definitions[nid].operation_id == "core.loop"]:
        body: Set[str] = set()
        stack = [e.target for e in outgoing.get(loop_id, []) if e.source_port == "item"]
        while stack:
            current = stack.pop()
            if current in body or current == loop_id:
                continue
            body.add(current)
            stack.extend(e.target for e in outgoing.get(current, []))
        loop_label = f"'{node_by_id[loop_id].label}' ({loop_id})"
        for nid in sorted(body, key=lambda n: position.get(n, 0)):
            d = definitions.get(nid)
            if nid in body_owner:
                add(ErrorCategory.GRAPH_VALIDATION, f"Node '{nid}' is inside more than one loop body.", node_id=nid)
            if d is not None and (d.is_trigger or d.operation_id in {"core.end", "core.loop"}):
                kind = "nested loops are not supported" if d.operation_id == "core.loop" else \
                    f"'{d.label}' nodes cannot run inside a loop body"
                add(ErrorCategory.GRAPH_VALIDATION, f"Node '{nid}' is in the body of loop {loop_label}: {kind}.",
                    node_id=nid, suggestion="Connect it after the loop's 'done' output instead.")
            for e in incoming.get(nid, []):
                if e.source not in body and e.source != loop_id:
                    add(ErrorCategory.GRAPH_VALIDATION,
                        f"Node '{nid}' in the body of loop {loop_label} also receives a connection from "
                        f"'{e.source}' outside the loop.", node_id=nid, edge_id=e.id,
                        suggestion="Feed loop-body nodes only from the loop's 'item' output or other body nodes; "
                                   "reference outside data with {{nodes.<id>.output...}}.")
                elif e.source == loop_id and e.source_port != "item":
                    add(ErrorCategory.GRAPH_VALIDATION,
                        f"Node '{nid}' is reachable from both the 'item' and 'done' outputs of loop {loop_label}.",
                        node_id=nid, edge_id=e.id)
        for e in outgoing.get(loop_id, []):
            if e.source_port == "done" and e.target in body:
                add(ErrorCategory.GRAPH_VALIDATION,
                    f"The 'done' output of loop {loop_label} leads into its own body ('{e.target}').", edge_id=e.id)
        loop_bodies[loop_id] = [nid for nid in order if nid in body]
        for nid in body:
            body_owner.setdefault(nid, loop_id)

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
                in_body = node.id in body_owner
                if expr.root == "item" and not in_body and not (source_name == "config" and top in lazy):
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' uses 'item', which is only available inside Filter rules and "
                        "inside a Loop Over Items body.",
                        node_id=node.id, field_=field_path)
                if expr.root == "loop" and not in_body:
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' uses 'loop', which is only available inside a Loop Over Items "
                        "body.", node_id=node.id, field_=field_path)
                ref = expr.node_id
                if ref is None:
                    continue
                if ref in body_owner and body_owner.get(node.id) != body_owner[ref]:
                    loop_id = body_owner[ref]
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' references '{ref}', which runs once per item inside loop "
                        f"'{loop_id}'.", node_id=node.id, field_=field_path,
                        suggestion=f"Use the collected results instead: {{{{nodes.{loop_id}.output.results}}}}.")
                    continue
                if ref not in index:
                    upstream = ancestors.get(node.id) or set(index) - {node.id}
                    add(ErrorCategory.INVALID_MAPPING,
                        f"'{{{{{raw.strip()}}}}}' references node '{ref}', which does not exist.",
                        node_id=node.id, field_=field_path,
                        suggestion=unknown_node_suggestion(ref, upstream))
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
        loop_bodies=loop_bodies,
        body_owner=body_owner,
    )
