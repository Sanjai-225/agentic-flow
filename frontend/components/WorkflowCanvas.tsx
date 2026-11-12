"use client";

import React, { useEffect, useMemo, useCallback } from "react";
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  Node,
  Edge,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { WorkflowResponse, WorkflowNode, WorkflowEdge, CustomNodeData } from "@/types/workflow";
import CustomNode from "@/components/CustomNode";

const nodeTypes = {
  custom: CustomNode,
};

interface WorkflowCanvasProps {
  workflow: WorkflowResponse | null;
  onFitViewTrigger?: (trigger: () => void) => void;
}

/**
 * Calculates a hierarchical top-to-bottom layout with horizontal branch spreading
 */
function calculateLayout(
  rawNodes: WorkflowNode[],
  rawEdges: WorkflowEdge[],
  startNodeIds: string[] = [],
  endNodeIds: string[] = []
): { nodes: Node<CustomNodeData>[]; edges: Edge[] } {
  if (!rawNodes || rawNodes.length === 0) {
    return { nodes: [], edges: [] };
  }

  const nodeMap = new Map<string, WorkflowNode>();
  rawNodes.forEach((n) => nodeMap.set(n.id, n));

  // Build adjacency
  const childrenMap = new Map<string, string[]>();
  const parentMap = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  rawNodes.forEach((n) => {
    childrenMap.set(n.id, []);
    parentMap.set(n.id, []);
    inDegree.set(n.id, 0);
  });

  rawEdges.forEach((e) => {
    if (nodeMap.has(e.source) && nodeMap.has(e.target)) {
      childrenMap.get(e.source)!.push(e.target);
      parentMap.get(e.target)!.push(e.source);
      inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
    }
  });

  // Identify roots
  let roots: string[] = [];
  if (startNodeIds && startNodeIds.length > 0) {
    roots = startNodeIds.filter((id) => nodeMap.has(id));
  }
  if (roots.length === 0) {
    roots = rawNodes.filter((n) => (inDegree.get(n.id) || 0) === 0).map((n) => n.id);
  }
  if (roots.length === 0) {
    roots = [rawNodes[0].id];
  }

  // BFS / Longest path level calculation
  const rankMap = new Map<string, number>();
  const queue: { id: string; rank: number }[] = [];
  const visited = new Set<string>();

  roots.forEach((rootId) => {
    rankMap.set(rootId, 0);
    queue.push({ id: rootId, rank: 0 });
    visited.add(rootId);
  });

  while (queue.length > 0) {
    const { id, rank } = queue.shift()!;
    const children = childrenMap.get(id) || [];
    for (const childId of children) {
      const nextRank = rank + 1;
      const currentRank = rankMap.get(childId) ?? -1;
      if (nextRank > currentRank) {
        rankMap.set(childId, nextRank);
      }
      if (!visited.has(childId)) {
        visited.add(childId);
        queue.push({ id: childId, rank: nextRank });
      }
    }
  }

  // Assign rank for unconnected nodes
  let maxRank = 0;
  rankMap.forEach((r) => {
    if (r > maxRank) maxRank = r;
  });

  rawNodes.forEach((n) => {
    if (!rankMap.has(n.id)) {
      maxRank += 1;
      rankMap.set(n.id, maxRank);
    }
  });

  // Group nodes by rank
  const ranks: Map<number, string[]> = new Map();
  rawNodes.forEach((n) => {
    const r = rankMap.get(n.id) || 0;
    if (!ranks.has(r)) ranks.set(r, []);
    ranks.get(r)!.push(n.id);
  });

  const sortedRankKeys = Array.from(ranks.keys()).sort((a, b) => a - b);

  // Spacing
  const VERTICAL_SPACING = 240;
  const HORIZONTAL_SPACING = 360;

  const positions = new Map<string, { x: number; y: number }>();

  sortedRankKeys.forEach((rankKey) => {
    const nodeIdsInRank = ranks.get(rankKey)!;

    // Sort nodes in this rank by parents' average X to minimize crossings
    if (rankKey > 0) {
      nodeIdsInRank.sort((a, b) => {
        const parentsA = parentMap.get(a) || [];
        const parentsB = parentMap.get(b) || [];
        const avgXA =
          parentsA.length > 0
            ? parentsA.reduce((sum, p) => sum + (positions.get(p)?.x || 0), 0) / parentsA.length
            : 0;
        const avgXB =
          parentsB.length > 0
            ? parentsB.reduce((sum, p) => sum + (positions.get(p)?.x || 0), 0) / parentsB.length
            : 0;
        return avgXA - avgXB;
      });
    }

    const count = nodeIdsInRank.length;
    nodeIdsInRank.forEach((id, index) => {
      const xOffset = (index - (count - 1) / 2) * HORIZONTAL_SPACING;
      const yOffset = rankKey * VERTICAL_SPACING + 80;
      positions.set(id, { x: xOffset, y: yOffset });
    });
  });

  const rfNodes: Node<CustomNodeData>[] = rawNodes.map((n) => {
    const pos = positions.get(n.id) || { x: 0, y: 0 };
    return {
      id: n.id,
      type: "custom",
      position: pos,
      data: {
        id: n.id,
        label: n.label || n.id,
        nodeType: n.type || "generic",
        description: n.description || "",
        tool: n.tool,
        config: n.config,
        isStart: startNodeIds.includes(n.id),
        isEnd: endNodeIds.includes(n.id),
      },
    };
  });

  const rfEdges: Edge[] = rawEdges.map((e, index) => ({
    id: e.id || `edge-${e.source}-${e.target}-${index}`,
    source: e.source,
    target: e.target,
    sourceHandle: e.source_handle,
    targetHandle: e.target_handle,
    animated: true,
    type: "smoothstep",
    label: e.label || e.condition,
    style: {
      stroke: "#6366f1",
      strokeWidth: 2,
    },
    labelStyle: {
      fill: "#e2e8f0",
      fontSize: 11,
      fontWeight: 500,
    },
    labelBgStyle: {
      fill: "#0f172a",
      fillOpacity: 0.95,
      stroke: "#334155",
      strokeWidth: 1,
    },
    labelBgPadding: [6, 4] as [number, number],
    labelBgBorderRadius: 6,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: "#6366f1",
      width: 16,
      height: 16,
    },
  }));

  return { nodes: rfNodes, edges: rfEdges };
}

function InnerWorkflowCanvas({
  workflow,
  onFitViewTrigger,
}: WorkflowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CustomNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const { fitView } = useReactFlow();

  const handleFitView = useCallback(() => {
    setTimeout(() => {
      fitView({ padding: 0.25, duration: 400 });
    }, 50);
  }, [fitView]);

  useEffect(() => {
    if (onFitViewTrigger) {
      onFitViewTrigger(handleFitView);
    }
  }, [onFitViewTrigger, handleFitView]);

  useEffect(() => {
    if (workflow && workflow.nodes && workflow.nodes.length > 0) {
      const layout = calculateLayout(
        workflow.nodes,
        workflow.edges || [],
        workflow.start_nodes || [],
        workflow.end_nodes || []
      );
      setNodes(layout.nodes);
      setEdges(layout.edges);
      handleFitView();
    } else {
      setNodes([]);
      setEdges([]);
    }
  }, [workflow, setNodes, setEdges, handleFitView]);

  return (
    <div className="relative w-full h-full min-h-[500px] bg-slate-950 overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        minZoom={0.2}
        maxZoom={1.5}
        defaultEdgeOptions={{
          type: "smoothstep",
        }}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1.5}
          color="#334155"
          className="opacity-60"
        />
        <Controls
          className="!bg-slate-900 !border-slate-800 !shadow-xl [&>button]:!bg-slate-900 [&>button]:!border-slate-800 [&>button]:!text-slate-300 [&>button:hover]:!bg-slate-800"
        />
        <MiniMap
          nodeColor={(n) => {
            const data = n.data as CustomNodeData | undefined;
            const t = (data?.nodeType || "").toLowerCase();
            if (t.includes("trigger")) return "#10b981";
            if (t.includes("llm") || t.includes("ai")) return "#a855f7";
            if (t.includes("condition")) return "#f59e0b";
            if (t.includes("action") || t.includes("tool")) return "#06b6d4";
            if (t.includes("output")) return "#f43f5e";
            return "#64748b";
          }}
          maskColor="rgba(15, 23, 42, 0.75)"
          className="!bg-slate-900 !border-slate-800 !rounded-lg !overflow-hidden !shadow-2xl"
        />
      </ReactFlow>

      {/* Empty State Overlay */}
      {(!workflow || !workflow.nodes || workflow.nodes.length === 0) && (
        <div className="absolute inset-0 pointer-events-none flex flex-col items-center justify-center p-6 text-center">
          <div className="w-16 h-16 mb-4 rounded-2xl bg-slate-900/80 border border-slate-800 flex items-center justify-center text-slate-500 shadow-xl backdrop-blur-sm">
            <svg
              className="w-8 h-8 stroke-current"
              fill="none"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"
              />
            </svg>
          </div>
          <h3 className="text-base font-medium text-slate-300 mb-1">
            Canvas is ready
          </h3>
          <p className="text-xs text-slate-500 max-w-sm">
            Describe your workflow requirement above and click &quot;Generate Workflow&quot; to visualize the connected node graph.
          </p>
        </div>
      )}
    </div>
  );
}

export default function WorkflowCanvas(props: WorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <InnerWorkflowCanvas {...props} />
    </ReactFlowProvider>
  );
}
