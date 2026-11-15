'use client';

import { useEffect, useMemo, useState } from 'react';

import {
  ConditionsEditor,
  ExpressionInput,
  JsonEditor,
  KeyValueEditor,
  SetFieldsEditor,
  getPath,
  setPath,
  useInsertTarget,
} from '@/components/editor/fields';
import { api } from '@/lib/api';
import { CATEGORY_COLOR } from '@/lib/status';
import { ancestorsOf, outputPaths } from '@/lib/workflowMapping';
import { useEditorStore } from '@/store/editorStore';
import type { ConfigField, CredentialSummary, NodeDefinition, WorkflowNode } from '@/types/workflow';

type Tab = 'parameters' | 'settings' | 'data' | 'json';

function FieldControl({
  field,
  config,
  onConfig,
  credentials,
}: {
  field: ConfigField;
  config: Record<string, any>;
  onConfig: (c: Record<string, any>) => void;
  credentials: CredentialSummary[];
}) {
  const value = getPath(config, field.key);
  const set = (v: unknown) => onConfig(setPath(config, field.key, v));
  switch (field.widget) {
    case 'select':
      return (
        <select aria-label={field.label} className="field" value={value ?? field.options?.[0] ?? ''} onChange={(e) => set(e.target.value)}>
          {(field.options || []).map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      );
    case 'boolean':
      return (
        <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <input aria-label={field.label} type="checkbox" checked={Boolean(value)} onChange={(e) => set(e.target.checked)} />
          {value ? 'Enabled' : 'Disabled'}
        </label>
      );
    case 'number':
      return <input aria-label={field.label} type="number" className="field" value={value ?? ''} onChange={(e) => set(e.target.value === '' ? undefined : Number(e.target.value))} />;
    case 'json':
      return <JsonEditor ariaLabel={field.label} value={value} onChange={set} />;
    case 'keyvalue':
      return <KeyValueEditor value={value} onChange={set} />;
    case 'conditions':
      return <ConditionsEditor value={value} onChange={set} />;
    case 'set_fields':
      return <SetFieldsEditor value={value} onChange={set} />;
    case 'credential':
      return (
        <select aria-label={field.label} className="field" value={value ?? ''} onChange={(e) => set(e.target.value || null)}>
          <option value="">Select a credential…</option>
          {credentials.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.type})
            </option>
          ))}
        </select>
      );
    case 'textarea':
    case 'expression':
      return <ExpressionInput ariaLabel={field.label} value={value} placeholder={field.placeholder} multiline={field.widget === 'textarea'} onChange={set} parse />;
    default:
      return <ExpressionInput ariaLabel={field.label} value={value} placeholder={field.placeholder} onChange={set} />;
  }
}

function visible(field: ConfigField, config: Record<string, any>): boolean {
  if (!field.show_if) return true;
  return Object.entries(field.show_if).every(([k, allowed]) => allowed.includes(String(getPath(config, k) ?? '')));
}

function WebhookSection({ workflowId }: { workflowId: string | null }) {
  const [info, setInfo] = useState<{ url: string; method: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!workflowId) return <p className="text-[11px] text-[var(--text-muted)]">Save the workflow to create its webhook URL.</p>;
  return (
    <div className="space-y-2 rounded-lg p-2.5" style={{ background: 'var(--surface-sunken)' }}>
      <p className="text-[11px] text-[var(--text-secondary)]">
        Requests to the secret URL start this workflow. The token is shown once; creating a new one revokes the old URL.
      </p>
      <button
        className="btn-ghost"
        onClick={async () => {
          try {
            setError(null);
            setInfo(await api.createWebhook(workflowId));
          } catch (e: any) {
            setError(e.message);
          }
        }}
      >
        {info ? 'Rotate webhook URL' : 'Create webhook URL'}
      </button>
      {info && (
        <div className="break-all font-mono text-[10px] text-[var(--accent-hover)]">
          {info.method} {info.url}
        </div>
      )}
      {error && <p className="text-[10px] text-[var(--danger)]">{error}</p>}
    </div>
  );
}

function DataPicker({ nodeId }: { nodeId: string }) {
  const edges = useEditorStore((s) => s.edges);
  const nodes = useEditorStore((s) => s.nodes);
  const execution = useEditorStore((s) => s.execution);
  const insert = useInsertTarget((s) => s.insert);
  const upstream = useMemo(() => ancestorsOf(nodeId, edges), [nodeId, edges]);
  const ordered = nodes.filter((n) => upstream.includes(n.id));
  if (!ordered.length) return <p className="text-[11px] text-[var(--text-muted)]">This node has no upstream nodes yet. Connect it to reference their outputs.</p>;
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-[var(--text-muted)]">
        Click a field to insert a reference into the last focused input. Output previews come from the selected execution; run the workflow to see real data.
      </p>
      {ordered.map((n) => {
        const run = execution?.nodes.find((r) => r.node_id === n.id);
        const paths = run?.status === 'success' ? outputPaths(n.id, run.output) : [{ path: '(entire output)', expr: `{{nodes.${n.id}.output}}`, preview: 'not run yet' }];
        return (
          <div key={n.id}>
            <p className="mb-1 text-[11px] font-semibold text-[var(--text-secondary)]">
              {n.data.node.label} <span className="font-mono text-[var(--text-muted)]">{n.id}</span>
            </p>
            <div className="flex flex-wrap gap-1">
              {paths.slice(0, 30).map((p) => (
                <button
                  key={p.expr}
                  title={p.expr}
                  className="rounded-md px-1.5 py-0.5 text-left font-mono text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  style={{ background: 'var(--surface-hover)' }}
                  onClick={() => (insert ? insert(p.expr) : navigator.clipboard?.writeText(p.expr))}
                >
                  {p.path} <span className="text-[var(--text-muted)]">{p.preview}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
      <p className="text-[10px] text-[var(--text-muted)]">
        Also available: <code>{'{{trigger.<field>}}'}</code>, <code>{'{{input.<field>}}'}</code> (previous node), <code>{'{{execution.id}}'}</code>.
      </p>
    </div>
  );
}

export default function NodeConfigPanel() {
  const selectedId = useEditorStore((s) => s.selectedNodeId);
  const flowNode = useEditorStore((s) => s.nodes.find((n) => n.id === s.selectedNodeId));
  const definition: NodeDefinition | undefined = useEditorStore((s) =>
    flowNode?.data.node.operation ? s.registryByOp[flowNode.data.node.operation] : undefined,
  );
  const issues = useEditorStore((s) => s.validation?.issues.filter((i) => i.node_id === s.selectedNodeId) ?? []);
  const workflowId = useEditorStore((s) => s.workflowId);
  const { updateNode, selectNode, deleteNode, duplicateNode } = useEditorStore.getState();
  const [tab, setTab] = useState<Tab>('parameters');
  const [credentials, setCredentials] = useState<CredentialSummary[]>([]);

  useEffect(() => {
    if (definition?.credentials?.length) api.listCredentials().then(setCredentials).catch(() => setCredentials([]));
  }, [definition?.operation_id, definition?.credentials?.length]);

  if (!selectedId || !flowNode) return null;
  const node: WorkflowNode = flowNode.data.node;
  const patch = (p: Partial<WorkflowNode>) => updateNode(node.id, p);
  const accent = definition ? CATEGORY_COLOR[definition.category] : '#94a3b8';

  return (
    <aside className="glass-strong absolute right-3 top-3 bottom-3 z-20 flex w-[400px] flex-col overflow-hidden rounded-2xl" aria-label="Node configuration">
      <div className="border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center justify-between">
          <span className="chip" style={{ color: accent, background: 'rgba(255,255,255,0.05)' }}>
            {definition?.label || node.type}
          </span>
          <div className="flex gap-1">
            <button className="btn-ghost px-2" title="Duplicate" onClick={() => duplicateNode(node.id)}>
              ⧉
            </button>
            <button className="btn-danger px-2" title="Delete" onClick={() => deleteNode(node.id)}>
              🗑
            </button>
            <button className="btn-ghost px-2" title="Close" onClick={() => selectNode(null)}>
              ✕
            </button>
          </div>
        </div>
        <input aria-label="Node label" className="mt-2 w-full bg-transparent text-sm font-semibold text-[var(--text-primary)] outline-none" value={node.label} onChange={(e) => patch({ label: e.target.value })} />
        <p className="font-mono text-[10px] text-[var(--text-muted)]">
          {node.id} · {node.operation || node.type}
        </p>
        {definition && <p className="mt-1 text-[11px] text-[var(--text-secondary)]">{definition.description}</p>}
        {!definition?.executable && (
          <p className="mt-2 rounded-md px-2 py-1.5 text-[11px] text-[var(--warning)]" style={{ background: 'rgba(251,191,36,0.1)' }}>
            This node is design-only and will be rejected before execution. Replace it with an executable node from the library.
          </p>
        )}
        {issues.length > 0 && (
          <ul className="mt-2 space-y-1">
            {issues.map((i, idx) => (
              <li key={idx} className="rounded-md px-2 py-1 text-[11px]" style={{ background: 'var(--error-light)', color: 'var(--danger)' }}>
                <b>{i.category}</b>
                {i.field ? ` · ${i.field}` : ''}: {i.message}
                {i.suggestion && <span className="block text-[var(--text-secondary)]">→ {i.suggestion}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex gap-1 border-b border-[var(--border)] px-3 pt-2">
        {(['parameters', 'settings', 'data', 'json'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-t-md px-2.5 py-1.5 text-[11px] font-medium capitalize ${tab === t ? 'text-[var(--text-primary)]' : 'text-[var(--text-muted)]'}`}
            style={tab === t ? { background: 'var(--surface-hover)' } : undefined}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {tab === 'parameters' && (
          <>
            {definition?.executable ? (
              definition.ui_fields.filter((f) => visible(f, node.config)).map((field) => (
                <div key={field.key}>
                  <label className="label">
                    {field.label}
                    {field.required && <span className="text-[var(--danger)]"> *</span>}
                  </label>
                  <FieldControl field={field} config={node.config} onConfig={(config) => patch({ config })} credentials={credentials} />
                  {field.help && <p className="mt-1 text-[10px] text-[var(--text-muted)]">{field.help}</p>}
                </div>
              ))
            ) : (
              <div>
                <label className="label">Design configuration</label>
                <JsonEditor value={node.config} onChange={(v) => patch({ config: (v as Record<string, any>) || {} })} />
              </div>
            )}
            {definition?.operation_id === 'core.webhook_trigger' && <WebhookSection workflowId={workflowId} />}
            <div>
              <label className="label">Description</label>
              <textarea className="field" rows={2} value={node.description} onChange={(e) => patch({ description: e.target.value })} />
            </div>
          </>
        )}

        {tab === 'settings' && (
          <>
            <div>
              <label className="label">On error</label>
              <select aria-label="On error" className="field" value={node.on_error || 'fail'} onChange={(e) => patch({ on_error: e.target.value as 'fail' | 'continue' })}>
                <option value="fail">Stop the workflow</option>
                <option value="continue">Continue (pass the error as output)</option>
              </select>
            </div>
            <div>
              <label className="label">Max attempts (including first)</label>
              <input
                aria-label="Max attempts"
                type="number"
                min={1}
                max={10}
                className="field"
                value={node.retry?.max_attempts ?? definition?.default_retry.max_attempts ?? 1}
                onChange={(e) =>
                  patch({
                    retry: { ...(node.retry || definition?.default_retry || { backoff_seconds: 1, backoff_multiplier: 2, max_backoff_seconds: 30 }), max_attempts: Math.min(10, Math.max(1, Number(e.target.value) || 1)) } as any,
                  })
                }
              />
              {definition?.side_effects && (
                <p className="mt-1 text-[10px] text-[var(--text-muted)]">
                  Retries only apply to retryable errors. Requests that change external state (POST, PUT, PATCH, DELETE) are never retried automatically, to avoid duplicate actions.
                </p>
              )}
            </div>
            <div>
              <label className="label">Retry backoff (seconds)</label>
              <input
                aria-label="Backoff seconds"
                type="number"
                min={0}
                step={0.5}
                className="field"
                value={node.retry?.backoff_seconds ?? definition?.default_retry.backoff_seconds ?? 1}
                onChange={(e) => patch({ retry: { ...(node.retry || definition?.default_retry || { max_attempts: 1, backoff_multiplier: 2, max_backoff_seconds: 30 }), backoff_seconds: Number(e.target.value) || 0 } as any })}
              />
            </div>
            <div>
              <label className="label">Node timeout (seconds)</label>
              <input
                aria-label="Node timeout"
                type="number"
                min={1}
                className="field"
                placeholder={String(definition?.default_timeout_seconds ?? 60)}
                value={node.timeout_seconds ?? ''}
                onChange={(e) => patch({ timeout_seconds: e.target.value === '' ? null : Number(e.target.value) })}
              />
            </div>
          </>
        )}

        {tab === 'data' && <DataPicker nodeId={node.id} />}

        {tab === 'json' && (
          <div>
            <label className="label">Canonical node (read-only)</label>
            <pre className="field-mono max-h-[60vh] overflow-auto whitespace-pre-wrap">{JSON.stringify(node, null, 2)}</pre>
          </div>
        )}
      </div>
    </aside>
  );
}
