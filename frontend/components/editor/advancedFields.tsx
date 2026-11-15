'use client';

/* Milestone 2 config widgets: model selection, agent tool allowlist, JSON Schema, form builder, schedule editor
 * and Switch cases. Every control edits the canonical node config; validation of record lives in the backend
 * (planner / config models), these editors only add immediate feedback. */

import { useEffect, useMemo, useState } from 'react';

import { ConditionsEditor, JsonEditor } from '@/components/editor/fields';
import { api } from '@/lib/api';
import type { AgentToolInfo, AIProviderInfo, CredentialSummary, SchedulePreview } from '@/types/workflow';

/* ---------- shared data (fetched once per page) ---------- */
let providersPromise: Promise<AIProviderInfo[]> | null = null;
let toolsPromise: Promise<AgentToolInfo[]> | null = null;

export function resetAdvancedFieldCaches() {
  providersPromise = null;
  toolsPromise = null;
}

function useProviders(): { providers: AIProviderInfo[]; error: string | null } {
  const [providers, setProviders] = useState<AIProviderInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    providersPromise ||= api.aiProviders();
    providersPromise
      .then((p) => alive && setProviders(p))
      .catch((e) => {
        providersPromise = null;
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, []);
  return { providers, error };
}

function useCredentials(): CredentialSummary[] {
  const [items, setItems] = useState<CredentialSummary[]>([]);
  useEffect(() => {
    let alive = true;
    api
      .listCredentials()
      .then((c) => alive && setItems(c))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, []);
  return items;
}

/* ---------- model_select ---------- */
export interface ModelTargetValue {
  provider: string;
  model: string;
  credential_id?: string | null;
  temperature?: number | null;
  max_output_tokens?: number;
  timeout_seconds?: number;
  reasoning_effort?: 'low' | 'medium' | 'high' | null;
}

export function ModelSelect({
  value,
  onChange,
  optional = false,
  ariaLabel = 'Model',
}: {
  value: ModelTargetValue | null | undefined;
  onChange: (v: ModelTargetValue | null) => void;
  optional?: boolean;
  ariaLabel?: string;
}) {
  const { providers, error } = useProviders();
  const credentials = useCredentials();
  const provider = providers.find((p) => p.id === value?.provider);
  const model = provider?.models.find((m) => m.model === value?.model);
  const caps = model?.capabilities;
  const set = (patch: Partial<ModelTargetValue>) => onChange({ ...(value as ModelTargetValue), ...patch });
  const pickProvider = (id: string) => {
    if (!id) return onChange(null);
    const p = providers.find((x) => x.id === id);
    const m = p?.models.find((x) => x.recommended) || p?.models[0];
    onChange({ provider: id, model: m?.model || '', credential_id: null, max_output_tokens: value?.max_output_tokens ?? 1024, timeout_seconds: value?.timeout_seconds ?? 60 });
  };
  const providerCreds = credentials.filter((c) => c.type === provider?.credential_type);

  return (
    <div className="space-y-1.5 rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }} data-testid={`${ariaLabel}-model-select`}>
      {error && <p className="text-[10px] text-[var(--danger)]">Could not load providers: {error}</p>}
      <div className="flex gap-1.5">
        <select aria-label={`${ariaLabel} provider`} className="field w-2/5" value={value?.provider ?? ''} onChange={(e) => pickProvider(e.target.value)}>
          {optional && <option value="">None</option>}
          {!optional && !value?.provider && <option value="">Provider…</option>}
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
          {value?.provider && !provider && providers.length > 0 && <option value={value.provider}>{value.provider} (unsupported)</option>}
        </select>
        {value?.provider && (
          <select aria-label={`${ariaLabel} model`} className="field flex-1" value={value.model} onChange={(e) => set({ model: e.target.value, temperature: null, reasoning_effort: null })}>
            {provider?.models.map((m) => (
              <option key={m.model} value={m.model}>
                {m.label}
                {m.recommended ? ' ★' : ''}
              </option>
            ))}
            {!model && <option value={value.model}>{value.model || 'Select a model'} (not supported)</option>}
          </select>
        )}
      </div>
      {value?.provider && (
        <>
          <select aria-label={`${ariaLabel} credential`} className="field" value={value.credential_id ?? ''} onChange={(e) => set({ credential_id: e.target.value || null })}>
            <option value="">{provider?.platform_key_available ? 'Platform key (server-configured)' : 'No credential selected (platform key unavailable)'}</option>
            {providerCreds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} {Object.values(c.hints).join(' ')}
              </option>
            ))}
          </select>
          {!value.credential_id && !provider?.platform_key_available && (
            <p className="text-[10px] text-[var(--warning)]">Add a {provider?.label} API key under Credentials, then select it here.</p>
          )}
          <div className="grid grid-cols-2 gap-1.5">
            <label className="text-[10px] text-[var(--text-muted)]">
              Max output tokens
              <input aria-label={`${ariaLabel} max output tokens`} type="number" min={1} max={caps?.max_output_tokens} className="field" value={value.max_output_tokens ?? 1024} onChange={(e) => set({ max_output_tokens: Number(e.target.value) || 1 })} />
            </label>
            <label className="text-[10px] text-[var(--text-muted)]">
              Timeout (s)
              <input aria-label={`${ariaLabel} timeout`} type="number" min={1} max={600} className="field" value={value.timeout_seconds ?? 60} onChange={(e) => set({ timeout_seconds: Number(e.target.value) || 60 })} />
            </label>
            {caps?.temperature && (
              <label className="text-[10px] text-[var(--text-muted)]">
                Temperature
                <input aria-label={`${ariaLabel} temperature`} type="number" min={0} max={2} step={0.1} className="field" value={value.temperature ?? ''} placeholder="default" onChange={(e) => set({ temperature: e.target.value === '' ? null : Number(e.target.value) })} />
              </label>
            )}
            {caps?.reasoning_effort && (
              <label className="text-[10px] text-[var(--text-muted)]">
                Reasoning effort
                <select aria-label={`${ariaLabel} reasoning effort`} className="field" value={value.reasoning_effort ?? ''} onChange={(e) => set({ reasoning_effort: (e.target.value || null) as ModelTargetValue['reasoning_effort'] })}>
                  <option value="">default</option>
                  <option value="low">low</option>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                </select>
              </label>
            )}
          </div>
          {caps && (
            <p className="text-[10px] text-[var(--text-muted)]">
              {(caps.context_window / 1000).toFixed(0)}K context · {(caps.max_output_tokens / 1000).toFixed(0)}K max output · tools {caps.tool_calling ? '✓' : '✗'} · JSON schema {caps.structured_output ? '✓' : '✗'}
              {caps.temperature ? '' : ' · temperature not supported'}
            </p>
          )}
        </>
      )}
    </div>
  );
}

/* ---------- tool_select ---------- */
export function ToolSelect({ value, onChange }: { value: string[] | undefined; onChange: (v: string[]) => void }) {
  const [tools, setTools] = useState<AgentToolInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    toolsPromise ||= api.aiTools();
    toolsPromise
      .then((t) => alive && setTools(t))
      .catch((e) => {
        toolsPromise = null;
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, []);
  const selected = new Set(value || []);
  const toggle = (id: string) => onChange(tools.map((t) => t.id).filter((t) => (t === id ? !selected.has(t) : selected.has(t))));
  return (
    <div className="space-y-1">
      {error && <p className="text-[10px] text-[var(--danger)]">Could not load tools: {error}</p>}
      {tools.map((t) => (
        <label key={t.id} className="flex items-start gap-2 rounded-md px-2 py-1 text-[11px]" style={{ background: 'var(--surface-sunken)' }}>
          <input type="checkbox" aria-label={`tool ${t.id}`} checked={selected.has(t.id)} onChange={() => toggle(t.id)} className="mt-0.5" />
          <span>
            <b className="font-mono text-[var(--text-primary)]">{t.id}</b>
            {t.permission !== 'read_only' && <span className="chip ml-1 text-[var(--warning)]">{t.permission}</span>}
            <span className="block text-[var(--text-muted)]">{t.description}</span>
          </span>
        </label>
      ))}
      {selected.size === 0 && <p className="text-[10px] text-[var(--text-muted)]">No tools: the agent can only reason over its inputs.</p>}
    </div>
  );
}

/* ---------- json_schema ---------- */
export function schemaProblem(schema: unknown): string | null {
  if (schema === null || schema === undefined) return null;
  if (typeof schema !== 'object' || Array.isArray(schema)) return 'The schema must be a JSON object.';
  const s = schema as Record<string, any>;
  if (s.type !== 'object') return 'The schema must describe an object ("type": "object").';
  if (!s.properties || typeof s.properties !== 'object' || !Object.keys(s.properties).length) return 'Add at least one property under "properties".';
  return null;
}

const EXAMPLE_SCHEMA = {
  type: 'object',
  properties: {
    category: { type: 'string', enum: ['billing', 'technical', 'account', 'general'] },
    priority: { type: 'string', enum: ['low', 'medium', 'high'] },
    summary: { type: 'string' },
  },
  required: ['category', 'priority', 'summary'],
};

export function JsonSchemaEditor({ value, onChange, ariaLabel }: { value: unknown; onChange: (v: unknown) => void; ariaLabel?: string }) {
  const problem = schemaProblem(value);
  return (
    <div className="space-y-1">
      <JsonEditor ariaLabel={ariaLabel} value={value ?? undefined} onChange={(v) => onChange(v ?? null)} />
      {problem && <p className="text-[10px] text-[var(--warning)]">{problem}</p>}
      {!value && (
        <button className="btn-ghost text-[11px]" onClick={() => onChange(EXAMPLE_SCHEMA)}>
          Insert example schema
        </button>
      )}
    </div>
  );
}

/* ---------- form_fields ---------- */
export interface FormFieldValue {
  key: string;
  label: string;
  type: 'text' | 'email' | 'number' | 'textarea' | 'select' | 'checkbox';
  required?: boolean;
  placeholder?: string | null;
  options?: string[];
  min?: number | null;
  max?: number | null;
  max_length?: number | null;
}

const FIELD_TYPES: FormFieldValue['type'][] = ['text', 'email', 'number', 'textarea', 'select', 'checkbox'];

export function slugKey(label: string, taken: string[]): string {
  const base = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, 'f_$1') || 'field';
  let key = base;
  let i = 2;
  while (taken.includes(key)) key = `${base}_${i++}`;
  return key.slice(0, 64);
}

export function FormFieldsEditor({ value, onChange }: { value: FormFieldValue[] | undefined; onChange: (v: FormFieldValue[]) => void }) {
  const fields = Array.isArray(value) ? value : [];
  const set = (idx: number, patch: Partial<FormFieldValue>) => onChange(fields.map((f, i) => (i === idx ? clean({ ...f, ...patch }) : f)));
  const move = (idx: number, delta: number) => {
    const next = [...fields];
    const [item] = next.splice(idx, 1);
    next.splice(Math.max(0, Math.min(next.length, idx + delta)), 0, item);
    onChange(next);
  };
  return (
    <div className="space-y-2">
      {fields.map((f, idx) => (
        <div key={idx} className="space-y-1.5 rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }}>
          <div className="flex gap-1.5">
            <input aria-label={`form field ${idx + 1} label`} className="field flex-1" placeholder="Label" value={f.label} onChange={(e) => set(idx, { label: e.target.value })} />
            <select aria-label={`form field ${idx + 1} type`} className="field w-28" value={f.type} onChange={(e) => set(idx, { type: e.target.value as FormFieldValue['type'] })}>
              {FIELD_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-1.5">
            <input aria-label={`form field ${idx + 1} key`} className="field-mono w-2/5" placeholder="key" value={f.key} onChange={(e) => set(idx, { key: e.target.value })} />
            <input aria-label={`form field ${idx + 1} placeholder`} className="field flex-1" placeholder="Placeholder (optional)" value={f.placeholder ?? ''} onChange={(e) => set(idx, { placeholder: e.target.value || null })} />
          </div>
          {f.type === 'select' && (
            <input aria-label={`form field ${idx + 1} options`} className="field" placeholder="Options, comma separated" value={(f.options || []).join(', ')} onChange={(e) => set(idx, { options: e.target.value.split(',').map((o) => o.trim()).filter(Boolean) })} />
          )}
          {f.type === 'number' && (
            <div className="flex gap-1.5">
              <input aria-label={`form field ${idx + 1} min`} type="number" className="field" placeholder="Min" value={f.min ?? ''} onChange={(e) => set(idx, { min: e.target.value === '' ? null : Number(e.target.value) })} />
              <input aria-label={`form field ${idx + 1} max`} type="number" className="field" placeholder="Max" value={f.max ?? ''} onChange={(e) => set(idx, { max: e.target.value === '' ? null : Number(e.target.value) })} />
            </div>
          )}
          {(f.type === 'text' || f.type === 'textarea') && (
            <input aria-label={`form field ${idx + 1} max length`} type="number" min={1} className="field" placeholder="Max length (optional)" value={f.max_length ?? ''} onChange={(e) => set(idx, { max_length: e.target.value === '' ? null : Number(e.target.value) })} />
          )}
          <div className="flex items-center justify-between text-[11px] text-[var(--text-secondary)]">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" aria-label={`form field ${idx + 1} required`} checked={Boolean(f.required)} onChange={(e) => set(idx, { required: e.target.checked })} />
              Required
            </label>
            <span className="flex gap-1">
              <button className="btn-ghost px-1.5" aria-label="move up" disabled={idx === 0} onClick={() => move(idx, -1)}>
                ↑
              </button>
              <button className="btn-ghost px-1.5" aria-label="move down" disabled={idx === fields.length - 1} onClick={() => move(idx, 1)}>
                ↓
              </button>
              <button className="btn-ghost px-1.5" aria-label="remove form field" onClick={() => onChange(fields.filter((_, i) => i !== idx))}>
                ✕
              </button>
            </span>
          </div>
        </div>
      ))}
      <button
        className="btn-ghost"
        onClick={() => {
          const label = `Field ${fields.length + 1}`;
          onChange([...fields, { key: slugKey(label, fields.map((f) => f.key)), label, type: 'text', required: false }]);
        }}
      >
        + Add field
      </button>
    </div>
  );
}

/** Drop keys that do not apply to the field type, so the backend config model accepts the field. */
function clean(f: FormFieldValue): FormFieldValue {
  const out: FormFieldValue = { key: f.key, label: f.label, type: f.type, required: Boolean(f.required) };
  if (f.placeholder) out.placeholder = f.placeholder;
  if (f.type === 'select') out.options = f.options || [];
  if (f.type === 'number') {
    if (f.min !== null && f.min !== undefined) out.min = f.min;
    if (f.max !== null && f.max !== undefined) out.max = f.max;
  }
  if ((f.type === 'text' || f.type === 'textarea') && f.max_length) out.max_length = f.max_length;
  return out;
}

/* ---------- schedule ---------- */
const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

export function describeSchedule(c: Record<string, any>): string {
  const time = `${String(c.hour ?? 9).padStart(2, '0')}:${String(c.minute ?? 0).padStart(2, '0')}`;
  switch (c.mode) {
    case 'interval':
      return `Every ${c.interval_minutes ?? 15} minute(s)`;
    case 'hourly':
      return `Every hour at minute ${c.minute ?? 0}`;
    case 'weekdays':
      return `Weekdays at ${time}`;
    case 'weekly':
      return `Every ${(c.weekdays || []).join(', ') || '(no day)'} at ${time}`;
    case 'cron':
      return `Cron: ${c.cron || '(empty)'}`;
    default:
      return `Every day at ${time}`;
  }
}

/** Format an ISO time in an IANA zone; falls back to UTC ISO while the user is still typing a zone name. */
export function formatInZone(iso: string, zone: string): string {
  try {
    return `${new Date(iso).toLocaleString(undefined, { timeZone: zone, dateStyle: 'medium', timeStyle: 'short' })} (${zone})`;
  } catch {
    return `${iso} (UTC)`;
  }
}

export function ScheduleEditor({ config, onConfig }: { config: Record<string, any>; onConfig: (c: Record<string, any>) => void }) {
  const [preview, setPreview] = useState<SchedulePreview | null>(null);
  const key = JSON.stringify(config);
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      api
        .schedulePreview(config)
        .then((p) => alive && setPreview(p))
        .catch((e) => alive && setPreview({ valid: false, errors: [e.message], next_runs: [] }));
    }, 300);
    return () => {
      alive = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const set = (patch: Record<string, any>) => onConfig({ ...config, ...patch });
  const mode = config.mode || 'daily';
  const zone = useMemo(() => (typeof Intl !== 'undefined' ? Intl.DateTimeFormat().resolvedOptions().timeZone : 'UTC'), []);
  return (
    <div className="space-y-2" data-testid="schedule-editor">
      <select aria-label="Schedule mode" className="field" value={mode} onChange={(e) => set({ mode: e.target.value })}>
        <option value="interval">Every N minutes</option>
        <option value="hourly">Hourly</option>
        <option value="daily">Daily</option>
        <option value="weekdays">Weekdays (Mon–Fri)</option>
        <option value="weekly">Weekly</option>
        <option value="cron">Custom cron</option>
      </select>
      {mode === 'interval' && (
        <input aria-label="Interval minutes" type="number" min={1} className="field" value={config.interval_minutes ?? 15} onChange={(e) => set({ interval_minutes: Number(e.target.value) || 1 })} />
      )}
      {['daily', 'weekdays', 'weekly'].includes(mode) && (
        <div className="flex gap-1.5">
          <input aria-label="Hour" type="number" min={0} max={23} className="field" value={config.hour ?? 9} onChange={(e) => set({ hour: Number(e.target.value) })} />
          <input aria-label="Minute" type="number" min={0} max={59} className="field" value={config.minute ?? 0} onChange={(e) => set({ minute: Number(e.target.value) })} />
        </div>
      )}
      {mode === 'hourly' && <input aria-label="Minute" type="number" min={0} max={59} className="field" value={config.minute ?? 0} onChange={(e) => set({ minute: Number(e.target.value) })} />}
      {mode === 'weekly' && (
        <div className="flex flex-wrap gap-1">
          {WEEKDAYS.map((d) => {
            const on = (config.weekdays || []).includes(d);
            return (
              <button key={d} aria-pressed={on} className={`chip ${on ? 'text-[var(--accent-hover)]' : 'text-[var(--text-muted)]'}`} onClick={() => set({ weekdays: on ? (config.weekdays || []).filter((x: string) => x !== d) : [...(config.weekdays || []), d] })}>
                {d}
              </button>
            );
          })}
        </div>
      )}
      {mode === 'cron' && <input aria-label="Cron expression" className="field-mono" placeholder="*/15 * * * *" value={config.cron ?? ''} onChange={(e) => set({ cron: e.target.value })} />}
      <div className="flex gap-1.5">
        <input aria-label="Time zone" className="field flex-1" placeholder="UTC" value={config.timezone ?? 'UTC'} onChange={(e) => set({ timezone: e.target.value })} />
        <button className="btn-ghost px-2 text-[10px]" title="Use my time zone" onClick={() => set({ timezone: zone })}>
          {zone}
        </button>
      </div>
      <div className="flex items-center justify-between text-[11px] text-[var(--text-secondary)]">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" aria-label="Schedule enabled" checked={config.enabled !== false} onChange={(e) => set({ enabled: e.target.checked })} />
          Enabled
        </label>
        <label className="flex items-center gap-1.5">
          After downtime
          <select aria-label="Misfire policy" className="field w-auto" value={config.misfire_policy ?? 'skip'} onChange={(e) => set({ misfire_policy: e.target.value })}>
            <option value="skip">skip missed runs</option>
            <option value="run_once">run once</option>
          </select>
        </label>
      </div>
      <div className="rounded-md p-2 text-[11px]" style={{ background: 'var(--surface-sunken)' }} data-testid="schedule-preview">
        <p className="font-medium text-[var(--text-primary)]">{describeSchedule(config)}</p>
        {preview && !preview.valid && preview.errors.map((e) => <p key={e} className="text-[var(--danger)]">{e}</p>)}
        {preview?.valid && (
          <ul className="mt-1 space-y-0.5 text-[var(--text-muted)]">
            {preview.next_runs.slice(0, 5).map((r) => (
              <li key={r}>{formatInZone(r, config.timezone || 'UTC')}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ---------- switch_cases ---------- */
interface SwitchCaseValue {
  key: string;
  label?: string;
  conditions: { combinator: 'all' | 'any'; rules: { left: unknown; operator: string; right?: unknown }[] };
}

export function SwitchCasesEditor({ value, onChange }: { value: SwitchCaseValue[] | undefined; onChange: (v: SwitchCaseValue[]) => void }) {
  const cases = Array.isArray(value) ? value : [];
  const set = (idx: number, patch: Partial<SwitchCaseValue>) => onChange(cases.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  return (
    <div className="space-y-2">
      {cases.map((c, idx) => (
        <div key={idx} className="space-y-1.5 rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }}>
          <div className="flex gap-1.5">
            <input aria-label={`case ${idx + 1} key`} className="field-mono w-2/5" placeholder="port key" value={c.key} onChange={(e) => set(idx, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })} />
            <input aria-label={`case ${idx + 1} label`} className="field flex-1" placeholder="Label" value={c.label ?? ''} onChange={(e) => set(idx, { label: e.target.value })} />
            <button className="btn-ghost px-2" aria-label="remove case" disabled={cases.length <= 1} onClick={() => onChange(cases.filter((_, i) => i !== idx))}>
              ✕
            </button>
          </div>
          <ConditionsEditor value={c.conditions as any} onChange={(v) => set(idx, { conditions: v as any })} />
        </div>
      ))}
      <button
        className="btn-ghost"
        onClick={() => {
          const taken = cases.map((c) => c.key);
          let n = cases.length + 1;
          while (taken.includes(`case_${n}`)) n += 1;
          onChange([...cases, { key: `case_${n}`, label: `Case ${n}`, conditions: { combinator: 'all', rules: [{ left: '', operator: 'eq', right: '' }] } }]);
        }}
      >
        + Add case
      </button>
      <p className="text-[10px] text-[var(--text-muted)]">Each case is an output port; data matching no case goes to <b>default</b>. Removing a case disconnects its edges.</p>
    </div>
  );
}
