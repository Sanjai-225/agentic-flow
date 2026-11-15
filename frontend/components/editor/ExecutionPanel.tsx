'use client';

import { useState } from 'react';

import { EXECUTION_STATUS_STYLE, NODE_STATUS_STYLE, formatDuration } from '@/lib/status';
import { useEditorStore, type BottomTab } from '@/store/editorStore';
import type { ExecutionDetail, NodeExecution } from '@/types/workflow';

function Json({ value }: { value: unknown }) {
  if (value === undefined || value === null) return <p className="text-[11px] text-[var(--text-muted)]">—</p>;
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-lg p-2 font-mono text-[10.5px] text-[var(--text-secondary)]" style={{ background: 'var(--surface-sunken)' }}>
      {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

function StatusDot({ color }: { color: string }) {
  return <span className="inline-block h-2 w-2 flex-shrink-0 rounded-full" style={{ background: color }} />;
}

type DetailTab = 'output' | 'input' | 'error' | 'logs' | 'ai' | 'iterations';

/** AI summary/trace for ai.generate / ai.agent (from metadata on success, error.details on failure). */
export function aiInfo(node: NodeExecution): { summary: any; trace: any[]; calls: any[] } | null {
  const meta = node.metadata || {};
  const details = node.error?.details || {};
  const summary = meta.ai || details.ai;
  const trace = meta.agent_trace || details.agent_trace || meta.trace || details.trace || [];
  const calls = meta.model_calls || details.model_calls || [];
  if (!summary && !trace.length && !calls.length) return null;
  return { summary, trace, calls };
}

export function AgentTrace({ node }: { node: NodeExecution }) {
  const info = aiInfo(node);
  if (!info) return <p className="text-[11px] text-[var(--text-muted)]">No AI activity recorded.</p>;
  const { summary, trace, calls } = info;
  const usage = summary?.usage || {};
  const toolCalls = trace.filter((t: any) => t.type === 'tool_call');
  const iterations = trace.filter((t: any) => t.type === 'model_call').length;
  return (
    <div className="space-y-2 text-[11px]" data-testid="agent-trace">
      {summary && (
        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[var(--text-secondary)]">
          <span>Requested: <b>{summary.requested?.provider}/{summary.requested?.model}</b></span>
          <span>Used: <b>{summary.provider}/{summary.model}</b> ({summary.credential_source} key)</span>
          <span>Fallback: {summary.fallback_used ? <b className="text-[var(--warning)]">used</b> : summary.fallback_configured ? 'configured, not used' : 'none'}</span>
          <span>Model calls: {calls.length}{iterations ? ` · agent iterations: ${iterations}` : ''}</span>
          <span>Tokens: {usage.total_tokens ?? 'not reported'}{usage.input_tokens != null ? ` (in ${usage.input_tokens} / out ${usage.output_tokens})` : ''}</span>
          {summary.fallback_reason && <span className="col-span-2 text-[var(--warning)]">Fallback reason: {summary.fallback_reason}</span>}
        </div>
      )}
      {toolCalls.length > 0 && (
        <table className="w-full text-left text-[10.5px]">
          <thead className="text-[var(--text-muted)]">
            <tr><th>#</th><th>Tool</th><th>Status</th><th>Arguments (redacted)</th><th>Result / reason</th><th>ms</th></tr>
          </thead>
          <tbody>
            {toolCalls.map((t: any, i: number) => (
              <tr key={i} className="align-top">
                <td>{i + 1}</td>
                <td className="font-mono">{t.tool}</td>
                <td className={t.status === 'success' ? 'text-[var(--success)]' : 'text-[var(--danger)]'}>{t.status}</td>
                <td className="max-w-[220px] break-all font-mono">{JSON.stringify(t.args ?? {})}</td>
                <td className="max-w-[260px] break-all">{t.result_summary || t.reason || ''}</td>
                <td>{t.duration_ms ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {calls.length > 0 && (
        <details>
          <summary className="cursor-pointer text-[var(--text-muted)]">Model calls ({calls.length})</summary>
          <Json value={calls} />
        </details>
      )}
      <p className="text-[10px] text-[var(--text-muted)]">Only tool calls, results and final outputs are recorded; model reasoning is never stored.</p>
    </div>
  );
}

export function LoopIterations({ node }: { node: NodeExecution }) {
  const meta = node.metadata || {};
  if (meta.loop && node.output) {
    const out = node.output;
    return (
      <div className="space-y-1 text-[11px]" data-testid="loop-iterations">
        <p className="text-[var(--text-secondary)]">{out.count} item(s): {out.succeeded} succeeded, {out.failed} failed.</p>
        {(out.errors || []).map((e: any) => (
          <p key={e.index} className="text-[var(--danger)]">Item {e.index} failed at {e.node_id}: {e.message}</p>
        ))}
        <Json value={out.results} />
      </div>
    );
  }
  const iterations: any[] = meta.iterations || [];
  return (
    <div className="space-y-1 text-[11px]" data-testid="loop-iterations">
      <p className="text-[var(--text-secondary)]">Ran in {meta.iteration_count ?? 0} iteration(s) of loop <code>{meta.loop_id}</code>{meta.iterations_truncated ? ' (first 100 shown)' : ''}.</p>
      <ul className="space-y-0.5">
        {iterations.map((it) => (
          <li key={it.index} className="font-mono text-[10.5px]">
            <span className={it.status === 'success' ? 'text-[var(--success)]' : it.status === 'failed' ? 'text-[var(--danger)]' : 'text-[var(--text-muted)]'}>#{it.index} {it.status}</span>{' '}
            {it.error || (it.output_preview !== undefined ? JSON.stringify(it.output_preview).slice(0, 200) : '')}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function NodeDetail({ node, execution }: { node: NodeExecution; execution: ExecutionDetail }) {
  const hasAi = Boolean(aiInfo(node));
  const hasIterations = Boolean(node.metadata?.loop || node.metadata?.iterations);
  const [tab, setTab] = useState<DetailTab>(node.error ? 'error' : hasAi ? 'ai' : 'output');
  const tabs: DetailTab[] = ['output', 'input', 'error', 'logs', ...(hasAi ? (['ai'] as DetailTab[]) : []), ...(hasIterations ? (['iterations'] as DetailTab[]) : [])];
  const logs = execution.logs.filter((l) => l.node_id === node.node_id);
  const style = NODE_STATUS_STYLE[node.status];
  return (
    <div className="flex h-full flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <StatusDot color={style.color} />
        <span className="font-semibold text-[var(--text-primary)]">{node.label}</span>
        <span className="font-mono text-[10px] text-[var(--text-muted)]">
          {node.node_id} · {node.operation}
        </span>
        <span style={{ color: style.color }}>{style.label}</span>
        <span className="text-[var(--text-muted)]">
          {formatDuration(node.duration_ms)}
          {node.attempts > 1 ? ` · ${node.attempts} attempts` : ''}
          {node.route ? ` · route: ${node.route.join(', ') || 'none'}` : ''}
        </span>
      </div>
      <div className="mb-2 flex gap-1">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-2 py-1 text-[11px] capitalize ${tab === t ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}
            style={tab === t ? { background: 'var(--surface-hover)' } : undefined}
          >
            {t === 'ai' ? 'AI / agent' : t}
            {t === 'error' && node.error ? ' ●' : ''}
            {t === 'logs' ? ` (${logs.length})` : ''}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-auto">
        {tab === 'output' && (node.status === 'skipped' ? <p className="text-[11px] text-[var(--text-muted)]">Skipped: {node.metadata?.skip_reason || 'not executed'}.</p> : <Json value={node.output} />)}
        {tab === 'input' && <Json value={node.inputs} />}
        {tab === 'ai' && <AgentTrace node={node} />}
        {tab === 'iterations' && <LoopIterations node={node} />}
        {tab === 'error' &&
          (node.error ? (
            <div className="space-y-2 text-[11px]" data-testid="node-error">
              <p className="text-[var(--danger)]">
                <b>{node.error.category}</b> — {node.error.message}
              </p>
              {node.error.field && (
                <p className="text-[var(--text-secondary)]">
                  Field: <code>{node.error.field}</code>
                </p>
              )}
              {node.error.suggestion && <p className="text-[var(--text-secondary)]">How to fix: {node.error.suggestion}</p>}
              <p className="text-[var(--text-muted)]">
                Retryable: {node.error.retryable ? 'yes' : 'no'} · Correlation ID: <code>{execution.correlation_id}</code>
              </p>
              {node.error.technical_detail && <Json value={node.error.technical_detail} />}
              {node.error.details && Object.keys(node.error.details).length > 0 && <Json value={node.error.details} />}
            </div>
          ) : (
            <p className="text-[11px] text-[var(--text-muted)]">No error.</p>
          ))}
        {tab === 'logs' && (
          <ul className="space-y-1 font-mono text-[10.5px]">
            {logs.length === 0 && <li className="text-[var(--text-muted)]">No logs.</li>}
            {logs.map((l, i) => (
              <li key={i} className={l.level === 'error' ? 'text-[var(--danger)]' : l.level === 'warning' ? 'text-[var(--warning)]' : 'text-[var(--text-secondary)]'}>
                {new Date(l.ts).toLocaleTimeString()} [{l.level}] {l.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ExecutionView() {
  const execution = useEditorStore((s) => s.execution);
  const inspected = useEditorStore((s) => s.inspectedNodeId);
  const inspect = useEditorStore((s) => s.inspectNode);
  const cancel = useEditorStore((s) => s.cancel);
  if (!execution) return <p className="p-4 text-xs text-[var(--text-muted)]">No execution selected. Click Run to start one, or pick a past run in History.</p>;
  const st = EXECUTION_STATUS_STYLE[execution.status];
  const selected = execution.nodes.find((n) => n.node_id === inspected) || execution.nodes.find((n) => n.status === 'failed') || execution.nodes[0];
  const active = execution.status === 'running' || execution.status === 'pending';
  return (
    <div className="flex h-full gap-3 p-3">
      <div className="flex w-[260px] flex-shrink-0 flex-col">
        <div className="mb-2 flex items-center gap-2 text-xs">
          <StatusDot color={st.color} />
          <span className="font-semibold" style={{ color: st.color }} data-testid="execution-status">
            {st.label}
          </span>
          <span className="text-[var(--text-muted)]">
            {formatDuration(execution.duration_ms)} · v{execution.workflow_version} · {execution.trigger_type}
          </span>
          {active && (
            <button className="btn-danger ml-auto px-2 py-0.5" onClick={cancel}>
              Cancel
            </button>
          )}
        </div>
        {execution.error && (
          <p className="mb-2 rounded-md px-2 py-1 text-[11px]" style={{ background: 'var(--error-light)', color: 'var(--danger)' }}>
            {execution.error.message}
          </p>
        )}
        <ul className="flex-1 space-y-0.5 overflow-y-auto">
          {execution.nodes.map((n) => {
            const ns = NODE_STATUS_STYLE[n.status];
            return (
              <li key={n.node_id}>
                <button
                  onClick={() => inspect(n.node_id)}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[11px] hover:bg-[var(--surface-hover)] ${selected?.node_id === n.node_id ? 'bg-[var(--surface-hover)]' : ''}`}
                >
                  <StatusDot color={ns.color} />
                  <span className="flex-1 truncate text-[var(--text-primary)]">{n.label}</span>
                  <span className="text-[var(--text-muted)]">{n.status === 'skipped' ? 'skipped' : formatDuration(n.duration_ms)}</span>
                </button>
              </li>
            );
          })}
        </ul>
        {execution.status === 'completed' && (
          <div className="mt-2">
            <p className="label">Workflow output</p>
            <Json value={execution.output} />
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">{selected ? <NodeDetail key={`${execution.id}-${selected.node_id}`} node={selected} execution={execution} /> : null}</div>
    </div>
  );
}

function HistoryView() {
  const executions = useEditorStore((s) => s.executions);
  const open = useEditorStore((s) => s.openExecution);
  const current = useEditorStore((s) => s.execution?.id);
  if (!executions.length) return <p className="p-4 text-xs text-[var(--text-muted)]">No executions yet.</p>;
  return (
    <ul className="space-y-0.5 overflow-y-auto p-3">
      {executions.map((e) => {
        const st = EXECUTION_STATUS_STYLE[e.status];
        return (
          <li key={e.id}>
            <button onClick={() => open(e.id)} className={`flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left text-[11px] hover:bg-[var(--surface-hover)] ${current === e.id ? 'bg-[var(--surface-hover)]' : ''}`}>
              <StatusDot color={st.color} />
              <span className="w-20" style={{ color: st.color }}>
                {st.label}
              </span>
              <span className="w-36 text-[var(--text-secondary)]">{e.created_at ? new Date(e.created_at).toLocaleString() : ''}</span>
              <span className="w-16 text-[var(--text-muted)]">v{e.workflow_version}</span>
              <span className="w-16 text-[var(--text-muted)]">{e.trigger_type}</span>
              <span className="w-16 text-[var(--text-muted)]">{formatDuration(e.duration_ms)}</span>
              <span className="flex-1 truncate text-[var(--danger)]">{e.error?.message || ''}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function ProblemsView() {
  const validation = useEditorStore((s) => s.validation);
  const select = useEditorStore((s) => s.selectNode);
  if (!validation) return <p className="p-4 text-xs text-[var(--text-muted)]">Click Validate to check the workflow.</p>;
  if (!validation.issues.length) return <p className="p-4 text-xs text-[var(--success)]">No problems — the workflow is ready to run.</p>;
  return (
    <ul className="space-y-1 overflow-y-auto p-3">
      {validation.issues.map((i, idx) => (
        <li key={idx}>
          <button onClick={() => i.node_id && select(i.node_id)} className="w-full rounded-md px-2 py-1.5 text-left text-[11px] hover:bg-[var(--surface-hover)]">
            <span className={i.severity === 'error' ? 'text-[var(--danger)]' : 'text-[var(--warning)]'}>
              {i.severity === 'error' ? '●' : '▲'} {i.category}
            </span>{' '}
            {i.node_id && <code className="text-[var(--text-muted)]">{i.node_id}</code>} <span className="text-[var(--text-primary)]">{i.message}</span>
            {i.suggestion && <span className="block pl-3 text-[var(--text-muted)]">→ {i.suggestion}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function ExecutionPanel() {
  const open = useEditorStore((s) => s.bottomOpen);
  const tab = useEditorStore((s) => s.bottomTab);
  const setBottom = useEditorStore((s) => s.setBottom);
  const problemCount = useEditorStore((s) => s.validation?.issues.filter((i) => i.severity === 'error').length ?? 0);
  const tabs: [BottomTab, string][] = [
    ['execution', 'Execution'],
    ['history', 'History'],
    ['problems', `Problems${problemCount ? ` (${problemCount})` : ''}`],
  ];
  return (
    <section className={`glass-strong flex flex-col rounded-2xl transition-all ${open ? 'h-[300px]' : 'h-10'}`} aria-label="Execution panel">
      <div className="flex items-center gap-1 border-b border-[var(--border)] px-3 py-1.5">
        {tabs.map(([t, label]) => (
          <button
            key={t}
            onClick={() => setBottom(true, t)}
            className={`rounded-md px-2.5 py-1 text-[11px] font-medium ${open && tab === t ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}
            style={open && tab === t ? { background: 'var(--surface-hover)' } : undefined}
          >
            {label}
          </button>
        ))}
        <button className="ml-auto text-[11px] text-[var(--text-muted)]" onClick={() => setBottom(!open)}>
          {open ? 'Collapse ▾' : 'Expand ▴'}
        </button>
      </div>
      {open && (
        <div className="min-h-0 flex-1 overflow-hidden">
          {tab === 'execution' && <ExecutionView />}
          {tab === 'history' && <HistoryView />}
          {tab === 'problems' && <ProblemsView />}
        </div>
      )}
    </section>
  );
}
