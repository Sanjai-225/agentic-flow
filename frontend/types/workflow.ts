/* Canonical workflow types (schema v2) — mirror backend/app/schemas/workflow.py */

export interface WorkflowTool {
  name: string;
  operation: string;
  status: string;
  purpose?: string;
}

export interface RetryPolicy {
  max_attempts: number;
  backoff_seconds: number;
  backoff_multiplier: number;
  max_backoff_seconds: number;
}

export interface NodeUI {
  position?: { x: number; y: number } | null;
  color?: string | null;
}

export interface WorkflowNode {
  id: string;
  type: string;
  operation?: string | null;
  type_version?: number;
  label: string;
  description: string;
  config: Record<string, any>;
  inputs?: Record<string, any>;
  retry?: RetryPolicy | null;
  timeout_seconds?: number | null;
  on_error?: 'fail' | 'continue';
  tool?: WorkflowTool | null;
  ui?: NodeUI;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  source_port?: string;
  target_port?: string;
  label?: string | null;
  condition?: string | null;
}

export interface WorkflowDefinition {
  schema_version?: number;
  workflow_id: string;
  version?: number;
  workflow_name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  start_nodes: string[];
  end_nodes: string[];
  settings?: Record<string, any>;
  ui?: Record<string, any>;
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

export type ErrorCategory =
  | 'SCHEMA_VALIDATION'
  | 'GRAPH_VALIDATION'
  | 'UNSUPPORTED_CAPABILITY'
  | 'MISSING_INPUT'
  | 'INVALID_MAPPING'
  | 'MISSING_CREDENTIALS'
  | 'AUTH_FAILURE'
  | 'PERMISSION_DENIED'
  | 'PROVIDER_ERROR'
  | 'MODEL_ERROR'
  | 'TIMEOUT'
  | 'RATE_LIMIT'
  | 'NODE_EXECUTION'
  | 'ENGINE_ERROR'
  | 'CANCELLED';

export interface ValidationIssue {
  category: ErrorCategory;
  message: string;
  severity: 'error' | 'warning';
  node_id?: string | null;
  edge_id?: string | null;
  field?: string | null;
  suggestion?: string | null;
}

export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
  order: string[];
  trigger_node_id: string | null;
}

/** Response of POST /api/workflows/generate (canonical v2 + review metadata). */
export interface WorkflowResponse extends WorkflowDefinition {
  review_status?: 'passed' | 'failed' | 'needs_clarification' | null;
  review_summary?: string | null;
  review_issues?: ReviewIssue[] | null;
  requirement_coverage?: RequirementCoverage[] | null;
  correction_attempts?: number;
  clarification_required?: boolean;
  execution_readiness?: { executable: boolean; issues: ValidationIssue[] };
}

/* ---------------- Registry ---------------- */

export interface PortDefinition {
  id: string;
  name: string;
  port_type: 'input' | 'output';
  data_type: string;
  description?: string;
  required?: boolean;
}

export interface ToolDefinition {
  name: string;
  operation: string;
  description: string;
}

export type ConfigWidget =
  | 'text'
  | 'textarea'
  | 'expression'
  | 'number'
  | 'boolean'
  | 'select'
  | 'json'
  | 'keyvalue'
  | 'conditions'
  | 'set_fields'
  | 'credential';

export interface ConfigField {
  key: string;
  label: string;
  widget: ConfigWidget;
  required?: boolean;
  options?: string[];
  placeholder?: string | null;
  help?: string | null;
  supports_expressions?: boolean;
  show_if?: Record<string, string[]> | null;
}

export interface NodeDefinition {
  node_type: string;
  operation_id: string;
  label: string;
  category: string;
  description: string;
  inputs: PortDefinition[];
  outputs: PortDefinition[];
  default_config: Record<string, any>;
  compatible_tools: ToolDefinition[];
  icon?: string;
  tags: string[];
  version: number;
  executable: boolean;
  status: 'ready' | 'design_only' | 'needs_config';
  aliases: string[];
  is_trigger: boolean;
  ports_in: string[];
  ports_out: string[];
  ui_fields: ConfigField[];
  config_schema: Record<string, any>;
  output_schema: Record<string, any>;
  credentials: string[];
  side_effects: boolean;
  idempotent: boolean;
  default_retry: RetryPolicy;
  default_timeout_seconds: number;
}

export interface RegistryCatalogResponse {
  total_nodes: number;
  categories: string[];
  nodes: NodeDefinition[];
}

/* ---------------- Persistence & execution ---------------- */

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  version: number;
  has_webhook: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_execution_status?: ExecutionStatus | null;
}

export interface WorkflowRecord extends WorkflowSummary {
  definition: WorkflowDefinition;
  validation: ValidationResult;
}

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'paused' | 'cancelled';
export type NodeRunStatus = 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'waiting';

export interface NodeError {
  category: ErrorCategory;
  message: string;
  technical_detail?: string | null;
  retryable: boolean;
  field?: string | null;
  suggestion?: string | null;
  node_id?: string | null;
  operation?: string | null;
  details?: Record<string, any>;
}

export interface NodeExecution {
  node_id: string;
  operation: string;
  label: string;
  position: number;
  status: NodeRunStatus;
  attempts: number;
  inputs: any;
  output: any;
  error: NodeError | null;
  route: string[] | null;
  metadata: Record<string, any> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface ExecutionLog {
  node_id: string | null;
  level: string;
  message: string;
  data: any;
  ts: string;
}

export interface ExecutionSummary {
  id: string;
  workflow_id: string;
  workflow_version: number;
  status: ExecutionStatus;
  trigger_type: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error: NodeError | null;
}

export interface ExecutionDetail extends ExecutionSummary {
  correlation_id: string;
  input: any;
  output: any;
  nodes: NodeExecution[];
  logs: ExecutionLog[];
  workflow_definition?: WorkflowDefinition | null;
}

export interface CredentialSummary {
  id: string;
  type: string;
  name: string;
  hints: Record<string, string>;
  created_at: string | null;
}

export const TERMINAL_STATUSES: ExecutionStatus[] = ['completed', 'failed', 'cancelled'];
