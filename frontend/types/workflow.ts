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

export interface RequirementCoverage {
  requirement_id: string;
  description: string;
  status: 'covered' | 'partially_covered' | 'missing' | 'unclear';
  evidence: string[];
  explanation: string;
}

export interface ReviewIssue {
  issue_type: string;
  severity: 'high' | 'medium' | 'low';
  requirement_id: string;
  affected_node_ids: string[];
  affected_edge_ids: string[];
  description: string;
  suggested_correction: string;
}

export interface WorkflowResponse {
  workflow_id: string;
  workflow_name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  start_nodes: string[];
  end_nodes: string[];
  // Review fields (optional)
  review_status?: 'passed' | 'failed' | 'needs_clarification' | null;
  review_summary?: string | null;
  review_issues?: ReviewIssue[] | null;
  requirement_coverage?: RequirementCoverage[] | null;
  correction_attempts?: number;
  clarification_required?: boolean;
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

// Node Registry (Phase 3) interfaces
export interface PortDefinition {
  id: string;
  name: string;
  port_type: 'input' | 'output';
  data_type: 'any' | 'string' | 'number' | 'boolean' | 'object' | 'array' | 'file';
  description?: string;
  required?: boolean;
}

export interface ToolDefinition {
  name: string;
  operation: string;
  description: string;
  required_params?: string[];
  optional_params?: string[];
}

export interface NodeDefinition {
  node_type: string;
  label: string;
  category: string;
  description: string;
  inputs: PortDefinition[];
  outputs: PortDefinition[];
  default_config: Record<string, any>;
  compatible_tools: ToolDefinition[];
  icon?: string;
  tags: string[];
}

export interface RegistryCatalogResponse {
  total_nodes: number;
  categories: string[];
  nodes: NodeDefinition[];
}
