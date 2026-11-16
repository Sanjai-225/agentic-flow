'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { AlertTriangle, Clock, TriangleAlert } from 'lucide-react';

import { NodeIconTile } from '@/lib/icons';
import { PORT_COLOR, portsFor } from '@/lib/ports';
import { NODE_STATUS_STYLE, categoryColor, formatDuration } from '@/lib/status';
import type { FlowNode } from '@/lib/workflowMapping';
import { useEditorStore } from '@/store/editorStore';
import type { LegacyNodeType, NodeDefinition, NodeExecution, ValidationIssue, WorkflowNode } from '@/types/workflow';

export interface WorkflowNodeViewProps {
  node: WorkflowNode;
  definition?: NodeDefinition;
  run?: Pick<NodeExecution, 'status' | 'duration_ms' | 'error' | 'attempts'> | null;
  issues?: ValidationIssue[];
  selected?: boolean;
  /** Set when the node uses a type removed from the library (preserved, never executable). */
  legacy?: LegacyNodeType;
}

/** The removed node type a canonical node refers to (operation, `unsupported:` prefix or type). */
export function legacyTypeOf(node: Pick<WorkflowNode, 'operation' | 'type'>, legacyTypes: Record<string, LegacyNodeType>): LegacyNodeType | undefined {
  const op = (node.operation || '').replace(/^unsupported:/, '');
  return legacyTypes[op] || (node.type ? legacyTypes[node.type] : undefined);
}

/** Pure presentational node card (unit-tested without React Flow state). */
export function WorkflowNodeView({ node, definition, run, issues = [], selected, legacy }: WorkflowNodeViewProps) {
  const executable = Boolean(definition?.executable);
  const accent = definition ? categoryColor(definition.category) : '#94a3b8';
  const status = run?.status;
  const statusStyle = status ? NODE_STATUS_STYLE[status] : null;
  const errorIssues = issues.filter((i) => i.severity === 'error');
  const isSkipped = status === 'skipped';

  const ring = statusStyle ? statusStyle.color : errorIssues.length ? 'var(--danger)' : selected ? 'var(--accent)' : null;
  const category = definition?.category || legacy?.category;

  return (
    <div
      data-testid={`node-${node.id}`}
      data-status={status || 'idle'}
      className={`relative w-[244px] overflow-hidden rounded-2xl border bg-[#131622]/90 backdrop-blur-xl transition-all duration-200 ${status === 'running' ? 'status-running' : ''}`}
      style={{
        borderColor: ring || 'rgba(255,255,255,0.1)',
        boxShadow: ring
          ? `0 0 0 1px ${ring}, 0 0 28px -4px ${ring}, 0 10px 40px rgba(0,0,0,0.6)`
          : '0 10px 40px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05)',
        opacity: isSkipped ? 0.45 : 1,
      }}
    >
      {/* Glowing category accent */}
      <div className="h-[3px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)`, boxShadow: `0 0 12px ${accent}` }} />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-16" style={{ background: `linear-gradient(180deg, ${accent}26, transparent)` }} />

      <div className="relative px-3.5 pb-3 pt-3">
        <div className="flex items-start gap-2.5">
          <NodeIconTile operation={node.operation} category={category} size={34} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold leading-tight tracking-tight text-[var(--text-primary)]" title={node.label}>
              {node.label}
            </p>
            <span className="mt-1 inline-block max-w-full truncate text-[10px] font-semibold uppercase tracking-wide" style={{ color: accent }}>
              {definition?.label || legacy?.label || node.type || 'Unknown'}
            </span>
          </div>
        </div>

        {!executable && (
          <p className="mt-2.5 flex items-start gap-1.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-2 py-1.5 text-[10px] font-medium text-[var(--warning)]">
            <TriangleAlert size={11} className="mt-px flex-shrink-0" />
            <span>
              {legacy
                ? 'Unsupported legacy node — replace it manually'
                : definition
                  ? 'Not executable'
                  : `Unknown operation (${node.operation || node.type}) — cannot execute`}
            </span>
          </p>
        )}
        {run?.error && (
          <p className="mt-2.5 line-clamp-2 rounded-lg border border-rose-500/20 bg-rose-500/10 px-2 py-1.5 text-[10px] text-rose-300" title={run.error.message}>
            {run.error.category}: {run.error.message}
          </p>
        )}
        {!run && errorIssues.length > 0 && (
          <p className="mt-2.5 flex items-start gap-1.5 rounded-lg border border-rose-500/20 bg-rose-500/10 px-2 py-1.5 text-[10px] text-rose-300" title={errorIssues[0].message}>
            <AlertTriangle size={11} className="mt-px flex-shrink-0" />
            <span className="line-clamp-2">
              {errorIssues.length} problem{errorIssues.length > 1 ? 's' : ''}: {errorIssues[0].message}
            </span>
          </p>
        )}

        <div className="mt-3 flex items-center gap-1.5 border-t border-white/[0.06] pt-2.5">
          <span className="mono-badge max-w-[110px] truncate">{node.id}</span>
          {run && run.status !== 'pending' && run.status !== 'skipped' && (
            <span className="flex items-center gap-1 font-mono text-[10px] text-[var(--text-muted)]">
              <Clock size={10} />
              {formatDuration(run.duration_ms)}
              {run.attempts > 1 ? ` · ${run.attempts} attempts` : ''}
            </span>
          )}
          {statusStyle && (
            <span
              className="ml-auto inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide"
              style={{ color: statusStyle.color, background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
              data-testid="node-status"
            >
              <span className={`h-1.5 w-1.5 rounded-full ${status === 'running' ? 'animate-pulse' : ''}`} style={{ background: statusStyle.color, boxShadow: `0 0 6px ${statusStyle.color}` }} />
              {statusStyle.label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function WorkflowNodeComponent({ id, data, selected }: NodeProps<FlowNode>) {
  const node = data.node;
  const definition = useEditorStore((s) => (node.operation ? s.registryByOp[node.operation] : undefined));
  const run = useEditorStore((s) => s.execution?.nodes.find((n) => n.node_id === id) ?? null);
  const issues = useEditorStore((s) => s.validation?.issues.filter((i) => i.node_id === id));
  const legacy = useEditorStore((s) => (definition ? undefined : legacyTypeOf(node, s.legacyTypes)));

  const { in: portsIn, out: portsOut } = portsFor(definition, node.config);

  return (
    <div className="relative">
      {portsIn.map((port, idx) => {
        const top = `${((idx + 1) / (portsIn.length + 1)) * 100}%`;
        return (
          <div key={`in-${port}`}>
            <Handle type="target" position={Position.Left} id={port} style={{ top }} />
            {portsIn.length > 1 && (
              <span className="pointer-events-none absolute -left-12 text-[9px] font-semibold uppercase text-[var(--text-muted)]" style={{ top: `calc(${top} - 7px)` }}>
                {port.replace('input_', 'in ')}
              </span>
            )}
          </div>
        );
      })}
      <WorkflowNodeView node={node} definition={definition} run={run} issues={issues} selected={selected} legacy={legacy} />
      {portsOut.map((port, idx) => {
        const top = `${((idx + 1) / (portsOut.length + 1)) * 100}%`;
        const color = PORT_COLOR[port];
        return (
          <div key={`out-${port}`}>
            <Handle type="source" position={Position.Right} id={port} style={color ? { top, borderColor: color, boxShadow: `0 0 8px ${color}` } : { top }} />
            {port !== 'main' && (
              <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap text-[9px] font-semibold uppercase" style={{ top: `calc(${top} - 7px)`, color }}>
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
