"""Graph validation for generated workflows.

Checks structural integrity (broken edge references, invalid start/end nodes,
unreachable/unconnected nodes, missing terminal paths) while allowing
legitimate conditional branching and controlled retry/loop paths that can
still reach an end node.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Set

from app.schemas.workflow import WorkflowSchema


@dataclass
class GraphValidationResult:
    """Result of validating a workflow's graph topology."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class GraphValidator:
    """Validates directed graph properties of a WorkflowSchema."""

    @staticmethod
    def validate(workflow: WorkflowSchema) -> GraphValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        node_ids: Set[str] = {node.id for node in workflow.nodes}
        adjacency: Dict[str, List[str]] = defaultdict(list)
        reverse_adjacency: Dict[str, List[str]] = defaultdict(list)

        # 1. Validate edge endpoints and build adjacency lists
        for edge in workflow.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge '{edge.id}' references missing source node '{edge.source}'.")
            if edge.target not in node_ids:
                errors.append(f"Edge '{edge.id}' references missing target node '{edge.target}'.")
            if edge.source == edge.target:
                errors.append(f"Edge '{edge.id}' forms a self-loop on node '{edge.source}'.")
            if edge.source in node_ids and edge.target in node_ids:
                adjacency[edge.source].append(edge.target)
                reverse_adjacency[edge.target].append(edge.source)

        # 2. Validate start_nodes and end_nodes
        if not workflow.start_nodes:
            errors.append("Workflow must define at least one start_node.")
        for start_id in workflow.start_nodes:
            if start_id not in node_ids:
                errors.append(f"start_nodes references missing node '{start_id}'.")

        if not workflow.end_nodes:
            errors.append("Workflow must define at least one end_node.")
        for end_id in workflow.end_nodes:
            if end_id not in node_ids:
                errors.append(f"end_nodes references missing node '{end_id}'.")

        # Stop early if basic node/edge references are broken
        if errors:
            return GraphValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 3. Check reachability from start_nodes (catches unconnected/orphan nodes)
        reachable_from_start = GraphValidator._bfs(workflow.start_nodes, adjacency)
        unreachable = sorted(node_ids - reachable_from_start)
        if unreachable:
            errors.append(
                f"Unreachable or unconnected nodes from start_nodes: {', '.join(unreachable)}."
            )

        # 4. Check that every end_node is reachable from at least one start_node
        unreachable_ends = sorted(set(workflow.end_nodes) - reachable_from_start)
        if unreachable_ends:
            errors.append(
                f"End nodes not reachable from any start_node: {', '.join(unreachable_ends)}."
            )

        # 5. Check reverse reachability from end_nodes (catches dead-ends and inescapable cycles)
        can_reach_end = GraphValidator._bfs(workflow.end_nodes, reverse_adjacency)
        no_terminal_path = sorted(node_ids - can_reach_end)
        if no_terminal_path:
            errors.append(
                f"Nodes with no path to any end_node (dead-end or trapped cycle): {', '.join(no_terminal_path)}."
            )

        # 6. Warn if a multi-node workflow has no edges at all
        if len(workflow.nodes) > 1 and not workflow.edges:
            errors.append("Multi-node workflow must contain edges connecting its nodes.")

        # 7. Detect cycles for informational warning (do not reject legitimate loops/retries
        #    as long as all nodes can reach an end_node, which step 5 already enforces).
        if GraphValidator._has_cycle(node_ids, adjacency):
            warnings.append("Workflow contains one or more cycles; ensure loop termination conditions are clear.")

        return GraphValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _bfs(seeds: List[str], graph: Dict[str, List[str]]) -> Set[str]:
        visited: Set[str] = set()
        queue: deque[str] = deque()
        for seed in seeds:
            if seed not in visited:
                visited.add(seed)
                queue.append(seed)

        while queue:
            current = queue.popleft()
            for neighbor in graph.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    @staticmethod
    def _has_cycle(node_ids: Set[str], adjacency: Dict[str, List[str]]) -> bool:
        # 0 = unvisited, 1 = visiting, 2 = visited
        state: Dict[str, int] = {node_id: 0 for node_id in node_ids}

        def dfs(node_id: str) -> bool:
            state[node_id] = 1
            for neighbor in adjacency.get(node_id, []):
                if state[neighbor] == 1:
                    return True
                if state[neighbor] == 0 and dfs(neighbor):
                    return True
            state[node_id] = 2
            return False

        return any(state[node_id] == 0 and dfs(node_id) for node_id in node_ids)
