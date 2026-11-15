'use client';

/*
 * Editor state. The canonical workflow is rebuilt from React Flow state on save/validate/run
 * (flowToCanonical). Execution state is ONLY ever set from backend responses.
 */

import { addEdge, applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange, type NodeChange } from '@xyflow/react';
import { create } from 'zustand';

import { api, ApiError, pollExecution } from '@/lib/api';
import {
  canonicalToFlow,
  edgeStyleFor,
  flowToCanonical,
  newNodeFromDefinition,
  uniqueEdgeId,
  uniqueNodeId,
  type FlowNode,
} from '@/lib/workflowMapping';
import type {
  ExecutionDetail,
  ExecutionSummary,
  LegacyNodeType,
  NodeDefinition,
  ValidationResult,
  WorkflowDefinition,
  WorkflowNode,
} from '@/types/workflow';

export type BottomTab = 'execution' | 'history' | 'problems';

interface EditorState {
  workflowId: string | null;
  /** Saved workflow's activation state (webhook/form/schedule triggers only fire when active). */
  active: boolean;
  name: string;
  description: string;
  version: number;
  dirty: boolean;
  nodes: FlowNode[];
  edges: Edge[];
  selectedNodeId: string | null;
  registry: NodeDefinition[];
  registryByOp: Record<string, NodeDefinition>;
  /** Category order as reported by the backend registry. */
  categories: string[];
  /** Removed node types, used to label preserved legacy nodes in old workflows. */
  legacyTypes: Record<string, LegacyNodeType>;
  validation: ValidationResult | null;
  execution: ExecutionDetail | null;
  executions: ExecutionSummary[];
  bottomOpen: boolean;
  bottomTab: BottomTab;
  inspectedNodeId: string | null;
  busy: null | 'saving' | 'validating' | 'starting';
  notice: { kind: 'info' | 'error' | 'success'; text: string } | null;
  pollController: AbortController | null;

  loadRegistry: () => Promise<void>;
  reset: () => void;
  loadDefinition: (def: WorkflowDefinition, opts?: { workflowId?: string | null; version?: number; dirty?: boolean }) => void;
  loadWorkflow: (id: string) => Promise<void>;
  setMeta: (patch: Partial<Pick<EditorState, 'name' | 'description'>>) => void;
  onNodesChange: (changes: NodeChange<FlowNode>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (conn: Connection) => void;
  addNode: (def: NodeDefinition, position?: { x: number; y: number }) => void;
  updateNode: (id: string, patch: Partial<WorkflowNode>) => void;
  duplicateNode: (id: string) => void;
  deleteNode: (id: string) => void;
  selectNode: (id: string | null) => void;
  toDefinition: () => WorkflowDefinition;
  save: () => Promise<string | null>;
  validate: () => Promise<ValidationResult | null>;
  run: (input: unknown) => Promise<void>;
  cancel: () => Promise<void>;
  openExecution: (id: string) => Promise<void>;
  refreshHistory: () => Promise<void>;
  setBottom: (open: boolean, tab?: BottomTab) => void;
  inspectNode: (id: string | null) => void;
  setNotice: (n: EditorState['notice']) => void;
  setActive: (active: boolean) => Promise<void>;
}

const initial = {
  workflowId: null,
  active: true,
  name: 'Untitled workflow',
  description: '',
  version: 0,
  dirty: false,
  nodes: [] as FlowNode[],
  edges: [] as Edge[],
  selectedNodeId: null,
  validation: null,
  execution: null,
  executions: [] as ExecutionSummary[],
  bottomOpen: false,
  bottomTab: 'execution' as BottomTab,
  inspectedNodeId: null,
  busy: null,
  notice: null,
  pollController: null,
};

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const issues = err.detail?.issues || err.detail?.errors;
    if (Array.isArray(issues) && issues.length) {
      return `${err.message} ${issues.slice(0, 3).map((i: any) => i.message || `${i.field}: ${i.message}`).join(' · ')}`;
    }
    return err.message;
  }
  return err instanceof Error ? err.message : String(err);
}

export const useEditorStore = create<EditorState>((set, get) => ({
  ...initial,
  registry: [],
  registryByOp: {},
  categories: [],
  legacyTypes: {},

  loadRegistry: async () => {
    if (get().registry.length) return;
    const [catalog, legacy] = await Promise.all([
      api.registry(),
      // Labels for legacy nodes are a nicety; the editor still works (and still blocks them) without them.
      api.legacyNodeTypes().catch(() => [] as LegacyNodeType[]),
    ]);
    const byOp: Record<string, NodeDefinition> = {};
    catalog.nodes.forEach((n) => (byOp[n.operation_id] = n));
    const legacyTypes: Record<string, LegacyNodeType> = {};
    (legacy || []).forEach((l) => (legacyTypes[l.node_type] = l));
    set({ registry: catalog.nodes, registryByOp: byOp, categories: catalog.categories || [], legacyTypes });
  },

  reset: () => {
    get().pollController?.abort();
    set({ ...initial });
  },

  loadDefinition: (def, opts = {}) => {
    get().pollController?.abort();
    const { nodes, edges } = canonicalToFlow(def);
    set({
      nodes,
      edges,
      name: def.workflow_name,
      description: def.description || '',
      workflowId: opts.workflowId === undefined ? get().workflowId : opts.workflowId,
      version: opts.version ?? def.version ?? 0,
      dirty: opts.dirty ?? false,
      selectedNodeId: null,
      validation: null,
      execution: null,
      inspectedNodeId: null,
      pollController: null,
    });
  },

  loadWorkflow: async (id) => {
    const record = await api.getWorkflow(id);
    get().loadDefinition(record.definition, { workflowId: record.id, version: record.version, dirty: false });
    set({ validation: record.validation, active: record.active !== false });
    await get().refreshHistory();
  },

  setMeta: (patch) => set({ ...patch, dirty: true }),

  onNodesChange: (changes) => {
    const meaningful = changes.some((c) => c.type !== 'select' && c.type !== 'dimensions');
    set({ nodes: applyNodeChanges(changes, get().nodes), ...(meaningful ? { dirty: true } : {}) });
    const removed = changes.filter((c) => c.type === 'remove').map((c) => (c as { id: string }).id);
    if (removed.includes(get().selectedNodeId || '')) set({ selectedNodeId: null });
  },

  onEdgesChange: (changes) => {
    const meaningful = changes.some((c) => c.type !== 'select');
    set({ edges: applyEdgeChanges(changes, get().edges), ...(meaningful ? { dirty: true } : {}) });
  },

  onConnect: (conn) => {
    if (!conn.source || !conn.target || conn.source === conn.target) return;
    const port = conn.sourceHandle || 'main';
    const duplicate = get().edges.some(
      (e) => e.source === conn.source && e.target === conn.target && (e.sourceHandle || 'main') === port,
    );
    if (duplicate) return;
    const edge: Edge = {
      ...conn,
      id: uniqueEdgeId(conn.source, conn.target, port),
      sourceHandle: port,
      targetHandle: conn.targetHandle || 'main',
      type: 'smoothstep',
      label: port !== 'main' ? port : undefined,
      style: edgeStyleFor(port),
    };
    set({ edges: addEdge(edge, get().edges), dirty: true });
  },

  addNode: (def, position) => {
    const existing = new Set(get().nodes.map((n) => n.id));
    const id = uniqueNodeId(def, existing);
    const last = get().nodes[get().nodes.length - 1];
    const pos = position || (last ? { x: last.position.x + 300, y: last.position.y } : { x: 0, y: 0 });
    const node: FlowNode = { id, type: 'workflow', position: pos, data: { node: newNodeFromDefinition(def, id) } };
    set({ nodes: [...get().nodes, node], selectedNodeId: id, dirty: true });
  },

  updateNode: (id, patch) => {
    set({
      nodes: get().nodes.map((n) => (n.id === id ? { ...n, data: { ...n.data, node: { ...n.data.node, ...patch } } } : n)),
      dirty: true,
    });
  },

  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id);
    if (!src) return;
    const def = get().registryByOp[src.data.node.operation || ''];
    const existing = new Set(get().nodes.map((n) => n.id));
    const newId = def ? uniqueNodeId(def, existing) : `${id}_copy`;
    const copy: FlowNode = {
      ...src,
      id: newId,
      selected: false,
      position: { x: src.position.x + 40, y: src.position.y + 80 },
      data: { node: { ...JSON.parse(JSON.stringify(src.data.node)), id: newId, label: `${src.data.node.label} (copy)` } },
    };
    set({ nodes: [...get().nodes, copy], selectedNodeId: newId, dirty: true });
  },

  deleteNode: (id) => {
    set({
      nodes: get().nodes.filter((n) => n.id !== id),
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      selectedNodeId: get().selectedNodeId === id ? null : get().selectedNodeId,
      dirty: true,
    });
  },

  selectNode: (id) => set({ selectedNodeId: id }),

  toDefinition: () => {
    const s = get();
    return flowToCanonical({ workflowId: s.workflowId, name: s.name, description: s.description, version: s.version }, s.nodes, s.edges);
  },

  save: async () => {
    const s = get();
    if (!s.nodes.length) {
      set({ notice: { kind: 'error', text: 'Add at least one node before saving.' } });
      return null;
    }
    set({ busy: 'saving' });
    try {
      const def = s.toDefinition();
      const record = s.workflowId ? await api.updateWorkflow(s.workflowId, def) : await api.createWorkflow(def);
      set({
        workflowId: record.id,
        version: record.version,
        dirty: false,
        active: record.active !== false,
        validation: record.validation,
        notice: { kind: 'success', text: `Saved version ${record.version}.` },
      });
      if (typeof window !== 'undefined' && !window.location.pathname.endsWith(record.id)) {
        window.history.replaceState(null, '', `/workflows/${record.id}`);
      }
      return record.id;
    } catch (err) {
      set({ notice: { kind: 'error', text: `Save failed: ${errorText(err)}` } });
      return null;
    } finally {
      set({ busy: null });
    }
  },

  validate: async () => {
    if (!get().nodes.length) return null;
    set({ busy: 'validating' });
    try {
      const result = await api.validate(get().toDefinition());
      set({
        validation: result,
        bottomOpen: true,
        bottomTab: 'problems',
        notice: result.valid
          ? { kind: 'success', text: 'Workflow is valid and ready to run.' }
          : { kind: 'error', text: `${result.issues.filter((i) => i.severity === 'error').length} problem(s) found.` },
      });
      return result;
    } catch (err) {
      set({ notice: { kind: 'error', text: `Validation failed: ${errorText(err)}` } });
      return null;
    } finally {
      set({ busy: null });
    }
  },

  run: async (input) => {
    let id = get().workflowId;
    if (!id || get().dirty) {
      id = await get().save();
      if (!id) return;
    }
    if (get().validation && !get().validation!.valid) {
      set({ bottomOpen: true, bottomTab: 'problems', notice: { kind: 'error', text: 'Fix the listed problems before running.' } });
      return;
    }
    set({ busy: 'starting' });
    try {
      const started = await api.run(id, input);
      set({ notice: { kind: 'info', text: 'Execution started.' } });
      await get().openExecution(started.execution_id);
    } catch (err) {
      set({ notice: { kind: 'error', text: `Run failed: ${errorText(err)}` }, bottomOpen: true, bottomTab: 'problems' });
      if (err instanceof ApiError && Array.isArray(err.detail?.issues)) {
        set({ validation: { valid: false, issues: err.detail.issues, order: [], trigger_node_id: null } });
      }
    } finally {
      set({ busy: null });
    }
  },

  cancel: async () => {
    const exec = get().execution;
    if (!exec) return;
    try {
      await api.cancelExecution(exec.id);
      set({ notice: { kind: 'info', text: 'Cancellation requested.' } });
    } catch (err) {
      set({ notice: { kind: 'error', text: `Cancel failed: ${errorText(err)}` } });
    }
  },

  openExecution: async (executionId) => {
    get().pollController?.abort();
    const controller = new AbortController();
    set({ pollController: controller, bottomOpen: true, bottomTab: 'execution' });
    try {
      const final = await pollExecution(executionId, (detail) => set({ execution: detail }), { signal: controller.signal });
      if (final) {
        await get().refreshHistory();
        set({
          notice:
            final.status === 'completed'
              ? { kind: 'success', text: 'Execution completed.' }
              : final.status === 'failed'
                ? { kind: 'error', text: `Execution failed: ${final.error?.message || 'see node details'}` }
                : { kind: 'info', text: `Execution ${final.status}.` },
        });
        const failedNode = final.nodes.find((n) => n.status === 'failed');
        if (failedNode) set({ inspectedNodeId: failedNode.node_id });
      }
    } catch (err) {
      set({ notice: { kind: 'error', text: `Could not load execution: ${errorText(err)}` } });
    }
  },

  refreshHistory: async () => {
    const id = get().workflowId;
    if (!id) return;
    try {
      set({ executions: await api.listExecutions(id) });
    } catch {
      /* history is non-critical */
    }
  },

  setBottom: (open, tab) => set({ bottomOpen: open, ...(tab ? { bottomTab: tab } : {}) }),
  inspectNode: (id) => set({ inspectedNodeId: id, bottomOpen: true, bottomTab: 'execution' }),
  setNotice: (n) => set({ notice: n }),

  setActive: async (active: boolean) => {
    const id = get().workflowId;
    if (!id) {
      set({ notice: { kind: 'error', text: 'Save the workflow before activating it.' } });
      return;
    }
    try {
      const summary = await api.setActive(id, active);
      set({
        active: summary.active !== false,
        notice: { kind: 'success', text: active ? 'Workflow activated: webhook, form and schedule triggers are live.' : 'Workflow deactivated: automatic triggers are paused.' },
      });
    } catch (err) {
      set({ notice: { kind: 'error', text: `Could not change activation: ${errorText(err)}` } });
    }
  },
}));
