import type { ExecutionStatus, NodeRunStatus } from '@/types/workflow';

export const NODE_STATUS_STYLE: Record<NodeRunStatus, { color: string; label: string }> = {
  pending: { color: 'var(--st-pending)', label: 'Pending' },
  running: { color: 'var(--st-running)', label: 'Running' },
  success: { color: 'var(--success)', label: 'Success' },
  failed: { color: 'var(--danger)', label: 'Failed' },
  skipped: { color: 'var(--st-skipped)', label: 'Skipped' },
  waiting: { color: 'var(--warning)', label: 'Waiting' },
};

export const EXECUTION_STATUS_STYLE: Record<ExecutionStatus, { color: string; label: string }> = {
  pending: { color: 'var(--st-pending)', label: 'Pending' },
  running: { color: 'var(--st-running)', label: 'Running' },
  completed: { color: 'var(--success)', label: 'Completed' },
  failed: { color: 'var(--danger)', label: 'Failed' },
  paused: { color: 'var(--warning)', label: 'Paused' },
  cancelled: { color: 'var(--st-skipped)', label: 'Cancelled' },
};

export const CATEGORY_COLOR: Record<string, string> = {
  input_output: '#f59e0b',
  logic: '#f97316',
  data_processing: '#22d3ee',
  tools: '#34d399',
  ai_agent: '#a78bfa',
  memory_knowledge: '#60a5fa',
  human_in_the_loop: '#f472b6',
};

/** Preferred display order; categories the backend adds later are appended, never dropped. */
export const CATEGORY_ORDER = ['input_output', 'ai_agent', 'data_processing', 'logic', 'tools', 'memory_knowledge', 'human_in_the_loop'];

export function categoryColor(category: string | undefined): string {
  return (category && CATEGORY_COLOR[category]) || '#94a3b8';
}

export function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] || category.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function orderCategories(present: string[]): string[] {
  const known = CATEGORY_ORDER.filter((c) => present.includes(c));
  return [...known, ...present.filter((c) => !CATEGORY_ORDER.includes(c)).sort()];
}

export const CATEGORY_LABEL: Record<string, string> = {
  input_output: 'Triggers & I/O',
  logic: 'Control flow',
  data_processing: 'Data',
  tools: 'HTTP & tools',
  ai_agent: 'AI',
  memory_knowledge: 'Knowledge',
  human_in_the_loop: 'Human in the loop',
};

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}
