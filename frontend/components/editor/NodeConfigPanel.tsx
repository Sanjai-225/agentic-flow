'use client';

import { useEffect, useMemo, useState } from 'react';
import { Copy, Trash2, X } from 'lucide-react';

import {
  ConditionsEditor,
  ExpressionInput,
  FIELD_DRAG_MIME,
  JsonEditor,
  JsonTemplateEditor,
  KeyValueEditor,
  SetFieldsEditor,
  getPath,
  setPath,
  useInsertTarget,
} from '@/components/editor/fields';
import { api } from '@/lib/api';
import { legacyTypeOf } from '@/components/CustomNode';
import { FormFieldsEditor, JsonSchemaEditor, ModelSelect, ScheduleEditor, SwitchCasesEditor, ToolSelect } from '@/components/editor/advancedFields';
import { NodeIconTile } from '@/lib/icons';
import { categoryColor } from '@/lib/status';
import { ancestorsOf, outputPaths } from '@/lib/workflowMapping';
import { useEditorStore } from '@/store/editorStore';
import type { ConfigField, CredentialSummary, FormInfo, InferredOutputFields, NodeDefinition, ScheduleInfo, WorkflowNode } from '@/types/workflow';

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
    case 'model_select':
      return <ModelSelect ariaLabel={field.label} value={value} optional={!field.required} onChange={set} />;
    case 'tool_select':
      return <ToolSelect value={value} onChange={set} />;
    case 'json_schema':
      return <JsonSchemaEditor ariaLabel={field.label} value={value} onChange={set} />;
    case 'form_fields':
      return <FormFieldsEditor value={value} onChange={set} />;
    case 'schedule':
      return <ScheduleEditor config={config} onConfig={onConfig} />;
    case 'switch_cases':
      return <SwitchCasesEditor value={value} onChange={set} />;
    case 'json_template':
      return <JsonTemplateEditor ariaLabel={field.label} value={value} placeholder={field.placeholder} onChange={set} />;
    case 'keyvalue':
      return <KeyValueEditor value={value} onChange={set} />;
    case 'keyvalue_json':
      return <KeyValueEditor value={value} onChange={set} jsonValues />;
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

const SOURCE_HINT: Record<InferredOutputFields['source'], string> = {
  config: 'expected, from config',
  schema: 'expected output',
  inherited: 'passed through',
  unknown: 'unknown',
};

/** Data-field hints for nodes that have not run yet (backend-inferred; nothing is executed). */
export function pickerPaths(
  nodeId: string,
  run: { status: string; output: unknown } | undefined,
  inferred: InferredOutputFields | undefined,
): { path: string; expr: string; preview: string }[] {
  if (run?.status === 'success') return outputPaths(nodeId, run.output);
  const whole = { path: '(entire output)', expr: `{{nodes.${nodeId}.output}}`, preview: 'not run yet' };
  if (!inferred?.fields.length) return [whole];
  const hint = SOURCE_HINT[inferred.source];
  return [whole, ...inferred.fields.map((f) => ({ path: f.path, expr: f.expr, preview: hint }))];
}

/** Public URL of a saved Form Submission Trigger (the backend creates it when the workflow is saved). */
function FormSection({ workflowId, nodeId, dirty }: { workflowId: string | null; nodeId: string; dirty: boolean }) {
  const [info, setInfo] = useState<FormInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!workflowId) return;
    let alive = true;
    api
      .listForms(workflowId)
      .then((forms) => alive && setInfo(forms.find((f) => f.node_id === nodeId) ?? null))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [workflowId, nodeId, dirty]);
  if (!workflowId) return <p className="text-[11px] text-[var(--text-muted)]">Save the workflow to publish its form.</p>;
  return (
    <div className="space-y-2 rounded-lg p-2.5" style={{ background: 'var(--surface-sunken)' }} data-testid="form-section">
      {!info && !error && <p className="text-[11px] text-[var(--text-muted)]">{dirty ? 'Save the workflow to publish this form.' : 'Loading form URL…'}</p>}
      {info && (
        <>
          <p className="text-[11px] text-[var(--text-secondary)]">Public form URL (anyone with the link can submit):</p>
          <a className="block break-all font-mono text-[10px] text-[var(--accent-hover)]" href={info.url} target="_blank" rel="noreferrer">
            {info.url}
          </a>
          {!info.workflow_active && <p className="text-[10px] text-[var(--warning)]">The workflow is inactive: the form is offline until you activate it.</p>}
          {dirty && <p className="text-[10px] text-[var(--warning)]">Unsaved changes are not visible on the public form until you save.</p>}
          <div className="flex gap-1.5">
            <button className="btn-ghost" onClick={() => navigator.clipboard?.writeText(info.url)}>
              Copy URL
            </button>
            <a className="btn-ghost" href={info.url} target="_blank" rel="noreferrer">
              Open preview
            </a>
            <button
              className="btn-ghost"
              onClick={async () => {
                try {
                  setInfo(await api.rotateForm(workflowId, nodeId));
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              New URL
            </button>
          </div>
        </>
      )}
      {error && <p className="text-[10px] text-[var(--danger)]">{error}</p>}
    </div>
  );
}

/** Persisted schedule state (next/last run, last status) from the backend scheduler. */
function ScheduleSection({ workflowId, nodeId, dirty }: { workflowId: string | null; nodeId: string; dirty: boolean }) {
  const [info, setInfo] = useState<ScheduleInfo | null>(null);
  useEffect(() => {
    if (!workflowId) return;
    let alive = true;
    api
      .listSchedules(workflowId)
      .then((rows) => alive && setInfo(rows.find((r) => r.node_id === nodeId) ?? null))
      .catch(() => alive && setInfo(null));
    return () => {
      alive = false;
    };
  }, [workflowId, nodeId, dirty]);
  if (!workflowId) return <p className="text-[11px] text-[var(--text-muted)]">Save the workflow to activate its schedule.</p>;
  const fmt = (v: string | null) => (v ? new Date(v).toLocaleString() : '—');
  return (
    <div className="space-y-1 rounded-lg p-2.5 text-[11px]" style={{ background: 'var(--surface-sunken)' }} data-testid="schedule-section">
      {!info && <p className="text-[var(--text-muted)]">{dirty ? 'Save to persist this schedule.' : 'No saved schedule yet.'}</p>}
      {info && (
        <>
          <p className="text-[var(--text-secondary)]">
            Status: <b>{!info.workflow_active ? 'workflow inactive' : info.enabled ? 'active' : 'disabled'}</b>
          </p>
          <p className="text-[var(--text-secondary)]">Next run: {info.enabled && info.workflow_active ? fmt(info.next_run_at) : '—'}</p>
          <p className="text-[var(--text-secondary)]">
            Last run: {fmt(info.last_run_at)} {info.last_status ? `(${info.last_status})` : ''}
          </p>
          {info.last_error && <p className="text-[var(--warning)]">{info.last_error}</p>}
          {dirty && <p className="text-[var(--warning)]">Unsaved changes take effect after you save.</p>}
        </>
      )}
    </div>
  );
}

/** Drag payload for a data reference. `text/plain` lets the browser drop it into any input/textarea natively. */
export function startFieldDrag(e: React.DragEvent, expr: string) {
  e.dataTransfer.setData('text/plain', expr);
  e.dataTransfer.setData(FIELD_DRAG_MIME, expr);
  e.dataTransfer.effectAllowed = 'copy';
  document.body.classList.add('af-dragging-field');
}

export function endFieldDrag() {
  document.body.classList.remove('af-dragging-field');
}

export function DataPicker({ nodeId, compact = false }: { nodeId: string; compact?: boolean }) {
  const edges = useEditorStore((s) => s.edges);
  const nodes = useEditorStore((s) => s.nodes);
  const execution = useEditorStore((s) => s.execution);
  const insert = useInsertTarget((s) => s.insert);
  const upstream = useMemo(() => ancestorsOf(nodeId, edges), [nodeId, edges]);
  const ordered = nodes.filter((n) => upstream.includes(n.id));
  const [inferred, setInferred] = useState<Record<string, InferredOutputFields>>({});
  // Re-infer when the graph or any node config changes (configs live on node.data.node).
  const graphKey = useMemo(
    () => JSON.stringify([nodes.map((n) => [n.id, n.data.node.operation, n.data.node.config]), edges.map((e) => [e.source, e.target])]),
    [nodes, edges],
  );
  useEffect(() => {
    let alive = true;
    api
      .outputFields(useEditorStore.getState().toDefinition())
      .then((res) => alive && setInferred(res.nodes))
      .catch(() => alive && setInferred({}));
    return () => {
      alive = false;
    };
  }, [graphKey]);
  if (!ordered.length) return <p className="text-[11px] text-[var(--text-muted)]">This node has no upstream nodes yet. Connect it to reference their outputs.</p>;
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-[var(--text-muted)]">
        <b>Drag</b> a field into any input below (or click it to insert into the last focused input).
        {!compact && " Before the first run, fields are inferred from each node's configuration; after a run, real output values are shown."}
      </p>
      {ordered.map((n) => {
        const run = execution?.nodes.find((r) => r.node_id === n.id);
        const paths = pickerPaths(n.id, run, inferred[n.id]);
        return (
          <div key={n.id}>
            <p className="mb-1 text-[11px] font-semibold text-[var(--text-secondary)]">
              {n.data.node.label} <span className="font-mono text-[var(--text-muted)]">{n.id}</span>
            </p>
            <div className="flex flex-wrap gap-1">
              {paths.slice(0, 30).map((p) => (
                <button
                  key={p.expr}
                  type="button"
                  draggable
                  data-testid={`field-chip-${p.expr}`}
                  title={`${p.expr}\nDrag into a field, or click to insert`}
                  className="cursor-grab rounded-md px-1.5 py-0.5 text-left font-mono text-[10px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] active:cursor-grabbing"
                  style={{ background: 'var(--surface-hover)' }}
                  onDragStart={(e) => startFieldDrag(e, p.expr)}
                  onDragEnd={endFieldDrag}
                  onClick={() => (insert ? insert(p.expr) : navigator.clipboard?.writeText(p.expr))}
                >
                  ⠿ {p.path} <span className="text-[var(--text-muted)]">{p.preview}</span>
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
  const dirty = useEditorStore((s) => s.dirty);
  const legacy = useEditorStore((s) => (flowNode && !definition ? legacyTypeOf(flowNode.data.node, s.legacyTypes) : undefined));
  const { updateNode, selectNode, deleteNode, duplicateNode } = useEditorStore.getState();
  const [tab, setTab] = useState<Tab>('parameters');
  const [credentials, setCredentials] = useState<CredentialSummary[]>([]);

  const allowedCredentialTypes = (definition?.credentials || []).join(',');
  useEffect(() => {
    const allowed = allowedCredentialTypes ? allowedCredentialTypes.split(',') : [];
    if (allowed.length)
      api
        .listCredentials()
        .then((cs) => setCredentials(cs.filter((c) => allowed.includes(c.type))))
        .catch(() => setCredentials([]));
  }, [allowedCredentialTypes]);

  if (!selectedId || !flowNode) return null;
  const node: WorkflowNode = flowNode.data.node;
  const patch = (p: Partial<WorkflowNode>) => updateNode(node.id, p);
  const accent = definition ? categoryColor(definition.category) : '#94a3b8';

  return (
    <aside className="hud animate-fade-up absolute bottom-2 right-2 top-[62px] z-30 flex w-[400px] max-w-[calc(100%-1rem)] flex-col overflow-hidden rounded-2xl sm:bottom-3 sm:right-3 sm:top-[72px]" aria-label="Node configuration">
      <div className="relative border-b border-[var(--border)] px-4 py-3" style={{ background: `linear-gradient(180deg, ${accent}1f, transparent)` }}>
        <div className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-2">
            <NodeIconTile operation={node.operation} category={definition?.category || legacy?.category} size={28} />
            <span className="chip truncate" style={{ color: accent, background: 'rgba(255,255,255,0.05)' }}>
              {definition?.label || legacy?.label || node.type}
            </span>
          </span>
          <div className="flex gap-0.5">
            <button className="btn-icon h-7 w-7" title="Duplicate" aria-label="Duplicate" onClick={() => duplicateNode(node.id)}>
              <Copy size={14} />
            </button>
            <button className="btn-icon h-7 w-7 hover:!bg-rose-500/10 hover:!text-rose-400" title="Delete" aria-label="Delete" onClick={() => deleteNode(node.id)}>
              <Trash2 size={14} />
            </button>
            <button className="btn-icon h-7 w-7" title="Close" aria-label="Close" onClick={() => selectNode(null)}>
              <X size={15} />
            </button>
          </div>
        </div>
        <input aria-label="Node label" className="mt-2.5 w-full rounded-md border border-transparent bg-transparent px-1 py-0.5 -mx-1 text-[15px] font-semibold tracking-tight text-[var(--text-primary)] outline-none transition-colors hover:border-white/[0.08] focus:border-indigo-400/40" value={node.label} onChange={(e) => patch({ label: e.target.value })} />
        <p className="font-mono text-[10px] text-[var(--text-muted)]">
          {node.id} · {node.operation || node.type}
        </p>
        {definition && <p className="mt-1 text-[11px] text-[var(--text-secondary)]">{definition.description}</p>}
        {!definition && (
          <div className="mt-2 space-y-1 rounded-md px-2 py-1.5 text-[11px] text-[var(--warning)]" style={{ background: 'rgba(251,191,36,0.1)' }} data-testid="legacy-notice">
            {legacy ? (
              <>
                <p>
                  <b>Unsupported legacy node.</b> &ldquo;{legacy.label}&rdquo; was removed from the node library because it could not execute. {legacy.reason}
                </p>
                {legacy.replacement && <p>→ {legacy.replacement}</p>}
              </>
            ) : (
              <p>
                <b>Unknown operation</b> <code>{node.operation || node.type}</code>. It is not in the node library and will be rejected before execution.
              </p>
            )}
            <p className="text-[var(--text-secondary)]">
              Its original configuration and connections are preserved below. Add a replacement node from the library, reconnect it, then delete this node.
            </p>
          </div>
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

      <div className="flex gap-1 border-b border-[var(--border)] px-3">
        {(['parameters', 'settings', 'data', 'json'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`relative -mb-px border-b-2 px-2.5 py-2 text-[11px] font-medium capitalize transition-colors ${tab === t ? 'border-indigo-400 text-[var(--text-primary)]' : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'}`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {tab === 'parameters' && (
          <>
            {definition && !definition.is_trigger && (
              <details open className="rounded-lg border border-[var(--border)] px-2.5 py-2" data-testid="input-data-panel">
                <summary className="cursor-pointer text-[11px] font-semibold text-[var(--text-secondary)]">Input data — drag fields into the boxes below</summary>
                <div className="mt-2 max-h-56 overflow-y-auto">
                  <DataPicker nodeId={node.id} compact />
                </div>
              </details>
            )}
            {definition ? (
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
                <label className="label">Original configuration (preserved)</label>
                <JsonEditor value={node.config} onChange={(v) => patch({ config: (v as Record<string, any>) || {} })} />
              </div>
            )}
            {definition?.operation_id === 'core.webhook_trigger' && <WebhookSection workflowId={workflowId} />}
            {definition?.operation_id === 'core.form_trigger' && <FormSection workflowId={workflowId} nodeId={node.id} dirty={dirty} />}
            {definition?.operation_id === 'core.schedule_trigger' && <ScheduleSection workflowId={workflowId} nodeId={node.id} dirty={dirty} />}
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
