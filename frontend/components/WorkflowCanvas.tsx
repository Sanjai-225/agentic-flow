'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import CustomNode from './CustomNode';
import { WorkflowResponse, CustomNodeData } from '@/types/workflow';

interface WorkflowCanvasProps {
  workflow: WorkflowResponse | null;
}

const nodeTypes = { custom: CustomNode };

/**
 * Auto-layout: topological sort with BFS, branching spread horizontally.
 */
function computeLayout(workflow: WorkflowResponse): { nodes: Node[]; edges: Edge[] } {
  const X_GAP = 320;
  const Y_GAP = 160;

  // Build adjacency
  const children: Record<string, string[]> = {};
  const parentCount: Record<string, number> = {};

  workflow.nodes.forEach((n) => {
    children[n.id] = [];
    parentCount[n.id] = 0;
  });
  workflow.edges.forEach((e) => {
    if (children[e.source]) children[e.source].push(e.target);
    parentCount[e.target] = (parentCount[e.target] || 0) + 1;
  });

  // BFS from start nodes
  const levels: Record<string, number> = {};
  const queue: string[] = [...workflow.start_nodes];
  queue.forEach((id) => (levels[id] = 0));

  while (queue.length > 0) {
    const current = queue.shift()!;
    const nextLevel = (levels[current] ?? 0) + 1;
    for (const child of children[current] || []) {
      if (levels[child] === undefined || nextLevel > levels[child]) {
        levels[child] = nextLevel;
      }
      parentCount[child]--;
      if (parentCount[child] <= 0) {
        queue.push(child);
      }
    }
  }

  // Assign remaining unvisited nodes
  workflow.nodes.forEach((n) => {
    if (levels[n.id] === undefined) levels[n.id] = 0;
  });

  // Group by level
  const levelGroups: Record<number, string[]> = {};
  Object.entries(levels).forEach(([id, level]) => {
    if (!levelGroups[level]) levelGroups[level] = [];
    levelGroups[level].push(id);
  });

  // Position nodes
  const nodeMap = new Map(workflow.nodes.map((n) => [n.id, n]));
  const startSet = new Set(workflow.start_nodes);
  const endSet = new Set(workflow.end_nodes);

  const flowNodes: Node[] = [];
  Object.entries(levelGroups).forEach(([levelStr, ids]) => {
    const level = parseInt(levelStr);
    const totalWidth = (ids.length - 1) * X_GAP;
    const startX = -totalWidth / 2;

    ids.forEach((id, idx) => {
      const n = nodeMap.get(id);
      if (!n) return;
      flowNodes.push({
        id: n.id,
        type: 'custom',
        position: { x: startX + idx * X_GAP, y: level * Y_GAP },
        data: {
          id: n.id,
          label: n.label,
          nodeType: n.type,
          description: n.description,
          config: n.config,
          tool: n.tool,
          isStart: startSet.has(n.id),
          isEnd: endSet.has(n.id),
        } as CustomNodeData,
      });
    });
  });

  const flowEdges: Edge[] = workflow.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_handle,
    targetHandle: e.target_handle,
    label: e.label || undefined,
    animated: true,
    type: 'smoothstep',
    style: { stroke: '#94a3b8', strokeWidth: 2 },
    labelStyle: { fontSize: 11, fontWeight: 500, fill: '#64748b' },
    labelBgStyle: { fill: '#ffffff', fillOpacity: 0.9 },
    labelBgPadding: [6, 4] as [number, number],
    labelBgBorderRadius: 4,
  }));

  return { nodes: flowNodes, edges: flowEdges };
}

export default function WorkflowCanvas({ workflow }: WorkflowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [rfInstance, setRfInstance] = useState<any>(null);

  useEffect(() => {
    if (!workflow) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const layout = computeLayout(workflow);
    setNodes(layout.nodes);
    setEdges(layout.edges);

    // Fit view after render
    setTimeout(() => rfInstance?.fitView({ padding: 0.15 }), 100);
  }, [workflow, rfInstance, setNodes, setEdges]);

  const onInit = useCallback((instance: any) => {
    setRfInstance(instance);
    instance.fitView({ padding: 0.15 });
  }, []);

  if (!workflow) {
    return (
      <div className="h-full flex items-center justify-center bg-[var(--background)]">
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-[var(--accent-light)] flex items-center justify-center">
            <svg className="w-8 h-8 text-[var(--accent)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0V12a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 12V5.25"
              />
            </svg>
          </div>
          <h3 className="text-base font-semibold text-[var(--text-primary)] mb-1">Workflow Canvas</h3>
          <p className="text-sm text-[var(--text-muted)] max-w-xs">
            Describe your automation in the chat and your workflow will appear here
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onInit={onInit}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        defaultEdgeOptions={{ animated: true, type: 'smoothstep' }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e2e8f0" />
        <Controls position="bottom-right" />
        <MiniMap
          position="bottom-left"
          nodeColor={(n) => {
            const t = (n.data as any)?.nodeType?.toLowerCase() || '';
            if (t.includes('trigger')) return '#eab308';
            if (t.includes('llm') || t.includes('ai')) return '#8b5cf6';
            if (t.includes('condition') || t.includes('decision')) return '#f97316';
            if (t.includes('database')) return '#10b981';
            if (t.includes('output') || t.includes('end')) return '#4f46e5';
            if (t.includes('notification')) return '#ec4899';
            return '#94a3b8';
          }}
          maskColor="rgba(0,0,0,0.05)"
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Workflow info badge */}
      <div className="absolute top-3 left-3 bg-white/90 backdrop-blur-sm border border-[var(--border)] rounded-lg px-3 py-2 shadow-sm">
        <p className="text-xs font-semibold text-[var(--text-primary)]">{workflow.workflow_name}</p>
        <p className="text-[10px] text-[var(--text-muted)]">
          {workflow.nodes.length} nodes · {workflow.edges.length} edges
        </p>
      </div>
    </div>
  );
}
