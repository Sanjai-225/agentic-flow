/*
 * Canonical workflow <-> React Flow conversion.
 * The canonical definition is the source of truth; React Flow only holds presentation state.
 * Node positions round-trip through node.ui.position (never read by the engine).
 */

import type { Edge, Node } from '@xyflow/react';
import type { NodeDefinition, NodeRunStatus, ValidationIssue, WorkflowDefinition, WorkflowNode } from '@/types/workflow';

export interface FlowNodeData extends Record<string, unknown> {
  node: WorkflowNode; // canonical node (ui stripped; position lives on the Flow node)
  runStatus?: NodeRunStatus;
  issues?: ValidationIssue[];
}

export type FlowNode = Node<FlowNodeData, 'workflow'>;

const X_GAP = 300;
const Y_GAP = 150;

/** Left-to-right layered layout used when a definition has no stored positions (e.g. AI output). */
export function autoLayout(def: Pick<WorkflowDefinition, 'nodes' | 'edges'>): Record<string, { x: number; y: number }> {
  const children: Record<string, string[]> = {};
  const indeg: Record<string, number> = {};
  def.nodes.forEach((n) => {
    children[n.id] = [];
    indeg[n.id] = 0;
  });
  def.edges.forEach((e) => {
    if (children[e.source] && e.target in indeg) {
      children[e.source].push(e.target);
      indeg[e.target] += 1;
    }
  });
  const level: Record<string, number> = {};
  const queue = def.nodes.filter((n) => indeg[n.id] === 0).map((n) => n.id);
  queue.forEach((id) => (level[id] = 0));
  const remaining = { ...indeg };
  while (queue.length) {
    const id = queue.shift()!;
    for (const child of children[id]) {
      level[child] = Math.max(level[child] ?? 0, (level[id] ?? 0) + 1);
      remaining[child] -= 1;
      if (remaining[child] === 0) queue.push(child);
    }
  }
  def.nodes.forEach((n) => {
    if (level[n.id] === undefined) level[n.id] = 0; // cycles / orphans
  });
  const columns: Record<number, string[]> = {};
  def.nodes.forEach((n) => {
    (columns[level[n.id]] ||= []).push(n.id);
  });
  const positions: Record<string, { x: number; y: number }> = {};
  Object.entries(columns).forEach(([lvl, ids]) => {
    const offset = ((ids.length - 1) * Y_GAP) / 2;
    ids.forEach((id, i) => {
      positions[id] = { x: Number(lvl) * X_GAP, y: i * Y_GAP - offset };
    });
  });
  return positions;
}

export function edgeStyleFor(port: string) {
  if (port === 'true') return { stroke: 'var(--success)', strokeWidth: 2 };
  if (port === 'false') return { stroke: 'var(--danger)', strokeWidth: 2 };
  return { stroke: 'var(--edge)', strokeWidth: 2 };
}

export function toFlowEdge(e: { id: string; source: string; target: string; source_port?: string; target_port?: string; label?: string | null }): Edge {
  const port = e.source_port || 'main';
  return {
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: port,
    targetHandle: e.target_port || 'main',
    label: e.label || (port !== 'main' ? port : undefined),
    type: 'smoothstep',
    style: edgeStyleFor(port),
  };
}

export function canonicalToFlow(def: WorkflowDefinition): { nodes: FlowNode[]; edges: Edge[] } {
  const hasAllPositions = def.nodes.length > 0 && def.nodes.every((n) => n.ui?.position);
  const layout = hasAllPositions ? {} : autoLayout(def);
  const nodes: FlowNode[] = def.nodes.map((n) => {
    const { ui, ...rest } = n;
    const position = hasAllPositions && ui?.position ? { x: ui.position.x, y: ui.position.y } : layout[n.id] || { x: 0, y: 0 };
    return {
      id: n.id,
      type: 'workflow',
      position,
      data: { node: { inputs: {}, on_error: 'fail', ...rest, config: rest.config ?? {} } },
    };
  });
  return { nodes, edges: def.edges.map(toFlowEdge) };
}

export function flowToCanonical(
  meta: { workflowId: string | null; name: string; description: string; version?: number },
  nodes: FlowNode[],
  edges: Edge[],
): WorkflowDefinition {
  return {
    schema_version: 2,
    workflow_id: meta.workflowId || 'draft',
    version: meta.version || 1,
    workflow_name: meta.name.trim() || 'Untitled workflow',
    description: meta.description,
    nodes: nodes.map((fn) => ({
      ...fn.data.node,
      ui: { position: { x: Math.round(fn.position.x), y: Math.round(fn.position.y) } },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      source_port: e.sourceHandle || 'main',
      target_port: e.targetHandle || 'main',
      label: typeof e.label === 'string' && !['true', 'false'].includes(e.label) ? e.label : null,
    })),
    // Derived by the backend from the graph topology.
    start_nodes: [],
    end_nodes: [],
  };
}

let counter = 0;
/** Predictable node ids: the smallest unused `<id_prefix>_<n>` (set_1, set_2, http_1, ...). */
export function uniqueNodeId(def: NodeDefinition, existing: Set<string>): string {
  const base = (def.id_prefix || def.operation_id.split('.').pop()!).replace(/[^a-z0-9_]/gi, '_');
  let i = 1;
  let id = `${base}_${i}`;
  while (existing.has(id)) {
    i += 1;
    id = `${base}_${i}`;
  }
  return id;
}

export function uniqueEdgeId(source: string, target: string, port: string): string {
  counter += 1;
  return `e_${source}_${port}_${target}_${Date.now().toString(36)}${counter}`;
}

export function newNodeFromDefinition(def: NodeDefinition, id: string): WorkflowNode {
  return {
    id,
    type: def.node_type,
    operation: def.operation_id,
    label: def.label,
    description: '',
    config: JSON.parse(JSON.stringify(def.default_config ?? {})),
    inputs: {},
    on_error: 'fail',
  };
}

/** Flatten an output value into `{{nodes.<id>.output...}}` expressions for the data picker. */
export function outputPaths(nodeId: string, value: unknown, maxDepth = 4): { path: string; expr: string; preview: string }[] {
  const out: { path: string; expr: string; preview: string }[] = [];
  const walk = (v: unknown, path: string, depth: number) => {
    const expr = `{{nodes.${nodeId}.output${path}}}`;
    const preview = v === null ? 'null' : typeof v === 'object' ? (Array.isArray(v) ? `array(${v.length})` : 'object') : String(v);
    out.push({ path: path || '(entire output)', expr, preview: preview.slice(0, 60) });
    if (depth >= maxDepth || v === null || typeof v !== 'object') return;
    if (Array.isArray(v)) {
      if (v.length) walk(v[0], `${path}[0]`, depth + 1);
      return;
    }
    Object.entries(v as Record<string, unknown>).slice(0, 40).forEach(([k, child]) => {
      const seg = /^[A-Za-z0-9_\-$]+$/.test(k) ? `.${k}` : `["${k}"]`;
      walk(child, `${path}${seg}`, depth + 1);
    });
  };
  walk(value, '', 0);
  return out;
}

/** Upstream ancestors of a node (expressions may only reference these). */
export function ancestorsOf(nodeId: string, edges: Edge[]): string[] {
  const parents: Record<string, string[]> = {};
  edges.forEach((e) => (parents[e.target] ||= []).push(e.source));
  const seen = new Set<string>();
  const stack = [...(parents[nodeId] || [])];
  while (stack.length) {
    const id = stack.pop()!;
    if (seen.has(id)) continue;
    seen.add(id);
    stack.push(...(parents[id] || []));
  }
  return Array.from(seen);
}
