'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';

import { CATEGORY_COLOR, NODE_STATUS_STYLE, formatDuration } from '@/lib/status';
import type { FlowNode } from '@/lib/workflowMapping';
import { useEditorStore } from '@/store/editorStore';
import type { NodeDefinition, NodeExecution, ValidationIssue, WorkflowNode } from '@/types/workflow';

export interface WorkflowNodeViewProps {
  node: WorkflowNode;
  definition?: NodeDefinition;
  run?: Pick<NodeExecution, 'status' | 'duration_ms' | 'error' | 'attempts'> | null;
  issues?: ValidationIssue[];
  selected?: boolean;
}

/** Pure presentational node card (unit-tested without React Flow state). */
export function WorkflowNodeView({ node, definition, run, issues = [], selected }: WorkflowNodeViewProps) {
  const executable = Boolean(definition?.executable);
  const accent = definition ? CATEGORY_COLOR[definition.category] || '#94a3b8' : '#94a3b8';
  const status = run?.status;
  const statusStyle = status ? NODE_STATUS_STYLE[status] : null;
  const errorIssues = issues.filter((i) => i.severity === 'error');
  const borderColor = statusStyle ? statusStyle.color : errorIssues.length ? 'var(--danger)' : selected ? 'var(--accent)' : 'var(--border-strong)';
  const isSkipped = status === 'skipped';

  return (
    <div
      data-testid={`node-${node.id}`}
      data-status={status || 'idle'}
      className={`relative w-[230px] rounded-xl glass-strong transition-opacity ${status === 'running' ? 'status-running' : ''}`}
      style={{ borderColor, borderWidth: status || selected || errorIssues.length ? 2 : 1, opacity: isSkipped ? 0.45 : 1 }}
    >
      <div className="h-1 rounded-t-xl" style={{ background: accent }} />
      <div className="px-3 py-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="chip" style={{ color: accent, background: 'rgba(255,255,255,0.05)' }}>
            {definition?.label || node.type || 'Unknown'}
          </span>
          {statusStyle && (
            <span className="chip" style={{ color: statusStyle.color, background: 'rgba(255,255,255,0.05)' }} data-testid="node-status">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: statusStyle.color }} />
              {statusStyle.label}
            </span>
          )}
        </div>
        <p className="mt-1.5 truncate text-[13px] font-semibold text-[var(--text-primary)]" title={node.label}>
          {node.label}
        </p>
        <p className="truncate text-[10px] font-mono text-[var(--text-muted)]">{node.id}</p>

        {!executable && (
          <p className="mt-1.5 rounded-md px-1.5 py-1 text-[10px] font-medium text-[var(--warning)]" style={{ background: 'rgba(251,191,36,0.1)' }}>
            {definition ? 'Design-only — cannot execute yet' : `Not executable (${node.operation || node.type})`}
          </p>
        )}
        {run?.error && (
          <p className="mt-1.5 line-clamp-2 text-[10px] text-[var(--danger)]" title={run.error.message}>
            {run.error.category}: {run.error.message}
          </p>
        )}
        {!run && errorIssues.length > 0 && (
          <p className="mt-1.5 line-clamp-2 text-[10px] text-[var(--danger)]" title={errorIssues[0].message}>
            {errorIssues.length} problem{errorIssues.length > 1 ? 's' : ''}: {errorIssues[0].message}
          </p>
        )}
        {run && run.status !== 'pending' && run.status !== 'skipped' && (
          <p className="mt-1 text-[10px] text-[var(--text-muted)]">
            {formatDuration(run.duration_ms)}
            {run.attempts > 1 ? ` · ${run.attempts} attempts` : ''}
          </p>
        )}
      </div>
    </div>
  );
}

function WorkflowNodeComponent({ id, data, selected }: NodeProps<FlowNode>) {
  const node = data.node;
  const definition = useEditorStore((s) => (node.operation ? s.registryByOp[node.operation] : undefined));
  const run = useEditorStore((s) => s.execution?.nodes.find((n) => n.node_id === id) ?? null);
  const issues = useEditorStore((s) => s.validation?.issues.filter((i) => i.node_id === id));

  const portsIn = definition ? definition.ports_in : ['main'];
  const portsOut = definition ? definition.ports_out : ['main'];

  return (
    <div className="relative">
      {portsIn.map((port) => (
        <Handle key={`in-${port}`} type="target" position={Position.Left} id={port} />
      ))}
      <WorkflowNodeView node={node} definition={definition} run={run} issues={issues} selected={selected} />
      {portsOut.map((port, idx) => {
        const top = `${((idx + 1) / (portsOut.length + 1)) * 100}%`;
        const color = port === 'true' ? 'var(--success)' : port === 'false' ? 'var(--danger)' : undefined;
        return (
          <div key={`out-${port}`}>
            <Handle type="source" position={Position.Right} id={port} style={{ top, background: color }} />
            {port !== 'main' && (
              <span className="pointer-events-none absolute -right-9 text-[9px] font-semibold uppercase" style={{ top: `calc(${top} - 7px)`, color }}>
                {port}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default memo(WorkflowNodeComponent);
