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
  | 'CANCELLED'
  | 'MODEL_UNAVAILABLE'
  | 'MODEL_AUTH'
  | 'MODEL_TIMEOUT'
  | 'UNSUPPORTED_MODEL'
  | 'INVALID_MODEL_OUTPUT'
  | 'STRUCTURED_OUTPUT_INVALID'
  | 'TOOL_NOT_ALLOWED'
  | 'TOOL_ARGS_INVALID'
  | 'TOOL_FAILED'
  | 'TOOL_TIMEOUT'
  | 'ITERATION_LIMIT'
  | 'USAGE_LIMIT';

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
  | 'credential'
  | 'json_template'
  | 'keyvalue_json'
  | 'model_select'
  | 'tool_select'
  | 'json_schema'
  | 'form_fields'
  | 'schedule'
  | 'switch_cases';

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
  /** Prefix for predictable node ids (<id_prefix>_<n>, e.g. set_1). */
  id_prefix?: string | null;
  /** Ports derived from the node config (Switch cases, Merge inputs); mirrors the backend planner. */
  dynamic_ports?: DynamicPorts | null;
  ai_guidance?: string | null;
}

export interface DynamicPorts {
  direction: 'in' | 'out';
  source: 'list' | 'count';
  config_key: string;
  key_field?: string | null;
  prefix?: string | null;
  fixed: string[];
  min_count: number;
  max_count: number;
}

/** Static output-field hints (POST /api/workflows/output-fields); real run outputs take precedence. */
export interface InferredOutputFields {
  source: 'config' | 'schema' | 'inherited' | 'unknown';
  fields: { path: string; expr: string }[];
}

/** A node type removed from the library (Milestone 2). Identification data only; never executable. */
export interface LegacyNodeType {
  node_type: string;
  label: string;
  category: string;
  description: string;
  reason: string;
  replacement?: string | null;
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
  /** Inactive workflows ignore webhook, form and schedule triggers (manual runs still work). */
  active?: boolean;
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
  provider?: string | null;
  created_at: string | null;
  updated_at?: string | null;
}

export interface CredentialTypeSpec {
  type: string;
  label: string;
  fields: string[];
  secret_fields: string[];
  provider: string | null;
  testable: boolean;
}

export interface CredentialTestResult {
  ok: boolean;
  message: string;
  provider?: string | null;
  category?: string | null;
  models_available: string[];
}

/* ---------------- AI providers / agent tools ---------------- */

export interface ModelCapabilities {
  tool_calling: boolean;
  structured_output: boolean;
  streaming: boolean;
  temperature: boolean;
  reasoning_effort: boolean;
  forced_tool_choice: boolean;
  usage_reporting: boolean;
  context_window: number;
  max_output_tokens: number;
}

export interface AIModelInfo {
  provider: string;
  model: string;
  label: string;
  capabilities: ModelCapabilities;
  verified: string;
  recommended: boolean;
}

export interface AIProviderInfo {
  id: string;
  label: string;
  credential_type: string;
  docs_url: string;
  platform_key_available: boolean;
  models: AIModelInfo[];
}

export interface AgentToolInfo {
  id: string;
  name: string;
  description: string;
  provider: string;
  permission: 'read_only' | 'network' | 'side_effect';
  side_effects: boolean;
  timeout_seconds: number;
  tags: string[];
}

/* ---------------- Triggers ---------------- */

export interface FormInfo {
  node_id: string;
  form_id: string;
  url: string;
  api_url: string;
  enabled: boolean;
  workflow_active: boolean;
}

export interface ScheduleInfo {
  schedule_id: string;
  node_id: string;
  enabled: boolean;
  workflow_active: boolean;
  timezone: string;
  spec: Record<string, any>;
  next_run_at: string | null;
  last_run_at: string | null;
  last_execution_id: string | null;
  last_status: string | null;
  last_error: string | null;
  upcoming: string[];
}

export interface SchedulePreview {
  valid: boolean;
  errors: string[];
  kind?: 'interval' | 'cron';
  expression?: string | null;
  next_runs: string[];
}

export interface PublicFormField {
  key: string;
  label: string;
  type: 'text' | 'email' | 'number' | 'textarea' | 'select' | 'checkbox';
  required: boolean;
  placeholder?: string;
  help?: string;
  options?: string[];
  min?: number;
  max?: number;
  min_length?: number;
  max_length?: number;
}

export interface PublicForm {
  form_id: string;
  title: string;
  description: string;
  submit_label: string;
  fields: PublicFormField[];
  honeypot_field: string;
}

export const TERMINAL_STATUSES: ExecutionStatus[] = ['completed', 'failed', 'cancelled'];
