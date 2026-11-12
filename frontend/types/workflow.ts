export interface WorkflowTool {
  name: string;
  operation: string;
  status: string;
  purpose?: string;
  inputs?: string[];
  outputs?: string[];
}

export interface WorkflowNode {
  id: string;
  type: string;
  label: string;
  description: string;
  config: Record<string, any>;
  tool?: WorkflowTool;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string;
  target_handle?: string;
  label?: string;
  condition?: string;
}

export interface WorkflowResponse {
  workflow_id: string;
  workflow_name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  start_nodes: string[];
  end_nodes: string[];
}

// React Flow node data payload for our CustomNode component
export interface CustomNodeData extends Record<string, unknown> {
  id: string;
  label: string;
  nodeType: string;
  description: string;
  config?: Record<string, any>;
  tool?: WorkflowTool;
  isStart?: boolean;
  isEnd?: boolean;
}
