'use client';

/* Config field widgets rendered from registry ui_fields. Expression-capable inputs register
 * themselves as the insertion target for the data picker ({{nodes.<id>.output...}}). */

import { useEffect, useRef, useState } from 'react';
import { create } from 'zustand';

export const OPERATORS: { value: string; label: string; unary?: boolean }[] = [
  { value: 'eq', label: 'equals' },
  { value: 'neq', label: 'not equals' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'does not contain' },
  { value: 'starts_with', label: 'starts with' },
  { value: 'ends_with', label: 'ends with' },
  { value: 'is_empty', label: 'is empty', unary: true },
  { value: 'not_empty', label: 'is not empty', unary: true },
  { value: 'is_true', label: 'is true', unary: true },
  { value: 'is_false', label: 'is false', unary: true },
  { value: 'regex', label: 'matches regex' },
];

/* ---------- insertion target for the data picker ---------- */
interface InsertTarget {
  insert: ((text: string) => void) | null;
  setInsert: (fn: ((text: string) => void) | null) => void;
}
export const useInsertTarget = create<InsertTarget>((set) => ({ insert: null, setInsert: (fn) => set({ insert: fn }) }));

/** Values typed by users are strings; turn obvious numbers/booleans back into JSON scalars. */
export function parseScalar(text: string): unknown {
  const t = text.trim();
  if (t === '') return '';
  if (t.includes('{{')) return text;
  if (t === 'true') return true;
  if (t === 'false') return false;
  if (t === 'null') return null;
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return text;
}

export function scalarToText(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function ExpressionInput({
  value,
  onChange,
  placeholder,
  multiline,
  ariaLabel,
  parse = false,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  placeholder?: string | null;
  multiline?: boolean;
  ariaLabel?: string;
  parse?: boolean;
}) {
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const setInsert = useInsertTarget((s) => s.setInsert);
  const text = scalarToText(value);
  const emit = (t: string) => onChange(parse ? parseScalar(t) : t);
  const onFocus = () =>
    setInsert((snippet: string) => {
      const el = ref.current;
      const current = el?.value ?? text;
      const start = el?.selectionStart ?? current.length;
      const end = el?.selectionEnd ?? current.length;
      emit(current.slice(0, start) + snippet + current.slice(end));
    });
  const hasExpr = text.includes('{{');
  const common = {
    ref,
    value: text,
    placeholder: placeholder || undefined,
    'aria-label': ariaLabel,
    onFocus,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => emit(e.target.value),
    className: `field-mono ${hasExpr ? 'text-[var(--accent-hover)]' : ''}`,
  };
  return multiline ? <textarea rows={3} {...common} /> : <input {...common} />;
}

export function JsonEditor({ value, onChange, ariaLabel }: { value: unknown; onChange: (v: unknown) => void; ariaLabel?: string }) {
  const [text, setText] = useState(() => (value === undefined ? '' : JSON.stringify(value, null, 2)));
  const [error, setError] = useState<string | null>(null);
  const last = useRef(value);
  useEffect(() => {
    if (JSON.stringify(value) !== JSON.stringify(last.current)) {
      setText(value === undefined ? '' : JSON.stringify(value, null, 2));
      last.current = value;
    }
  }, [value]);
  const commit = () => {
    if (!text.trim()) {
      setError(null);
      last.current = null;
      onChange(null);
      return;
    }
    try {
      const parsed = JSON.parse(text);
      setError(null);
      last.current = parsed;
      onChange(parsed);
    } catch (e: any) {
      setError(`Invalid JSON: ${e.message}`);
    }
  };
  return (
    <div>
      <textarea aria-label={ariaLabel} rows={5} className="field-mono" value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} />
      {error && <p className="mt-1 text-[10px] text-[var(--danger)]">{error}</p>}
    </div>
  );
}

export function KeyValueEditor({ value, onChange }: { value: Record<string, unknown> | undefined; onChange: (v: Record<string, unknown>) => void }) {
  const entries = Object.entries(value || {});
  const update = (rows: [string, unknown][]) => onChange(Object.fromEntries(rows.filter(([k]) => k !== '' || rows.length === 1)));
  return (
    <div className="space-y-1.5">
      {entries.map(([k, v], idx) => (
        <div key={idx} className="flex gap-1.5">
          <input
            aria-label="key"
            className="field-mono w-2/5"
            value={k}
            onChange={(e) => update(entries.map((row, i) => (i === idx ? [e.target.value, row[1]] : row)))}
          />
          <div className="flex-1">
            <ExpressionInput ariaLabel="value" parse value={v} onChange={(nv) => update(entries.map((row, i) => (i === idx ? [row[0], nv] : row)))} />
          </div>
          <button className="btn-ghost px-2" aria-label="remove" onClick={() => update(entries.filter((_, i) => i !== idx))}>
            ✕
          </button>
        </div>
      ))}
      <button className="btn-ghost" onClick={() => onChange({ ...(value || {}), [`key${entries.length + 1}`]: '' })}>
        + Add
      </button>
    </div>
  );
}

interface Rule {
  left: unknown;
  operator: string;
  right?: unknown;
}
interface Conditions {
  combinator: 'all' | 'any';
  rules: Rule[];
}

export function ConditionsEditor({ value, onChange }: { value: Conditions | undefined; onChange: (v: Conditions) => void }) {
  const cond: Conditions = value && Array.isArray(value.rules) ? value : { combinator: 'all', rules: [] };
  const setRule = (idx: number, patch: Partial<Rule>) =>
    onChange({ ...cond, rules: cond.rules.map((r, i) => (i === idx ? { ...r, ...patch } : r)) });
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[11px] text-[var(--text-secondary)]">
        Match
        <select aria-label="combinator" className="field w-auto" value={cond.combinator} onChange={(e) => onChange({ ...cond, combinator: e.target.value as 'all' | 'any' })}>
          <option value="all">all rules</option>
          <option value="any">any rule</option>
        </select>
      </div>
      {cond.rules.map((rule, idx) => {
        const unary = OPERATORS.find((o) => o.value === rule.operator)?.unary;
        return (
          <div key={idx} className="space-y-1.5 rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }}>
            <ExpressionInput ariaLabel={`rule ${idx + 1} left`} parse value={rule.left} placeholder="{{nodes.set_1.output.amount}}" onChange={(v) => setRule(idx, { left: v })} />
            <div className="flex gap-1.5">
              <select aria-label={`rule ${idx + 1} operator`} className="field w-1/2" value={rule.operator} onChange={(e) => setRule(idx, { operator: e.target.value })}>
                {OPERATORS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {!unary && (
                <div className="flex-1">
                  <ExpressionInput ariaLabel={`rule ${idx + 1} right`} parse value={rule.right} placeholder="value" onChange={(v) => setRule(idx, { right: v })} />
                </div>
              )}
              <button className="btn-ghost px-2" aria-label="remove rule" disabled={cond.rules.length <= 1} onClick={() => onChange({ ...cond, rules: cond.rules.filter((_, i) => i !== idx) })}>
                ✕
              </button>
            </div>
          </div>
        );
      })}
      <button className="btn-ghost" onClick={() => onChange({ ...cond, rules: [...cond.rules, { left: '', operator: 'eq', right: '' }] })}>
        + Add rule
      </button>
    </div>
  );
}

interface SetField {
  name: string;
  value: unknown;
  type: string;
}

export function SetFieldsEditor({ value, onChange }: { value: SetField[] | undefined; onChange: (v: SetField[]) => void }) {
  const fields = Array.isArray(value) ? value : [];
  const setField = (idx: number, patch: Partial<SetField>) => onChange(fields.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  return (
    <div className="space-y-2">
      {fields.map((f, idx) => (
        <div key={idx} className="space-y-1.5 rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }}>
          <div className="flex gap-1.5">
            <input aria-label={`field ${idx + 1} name`} className="field-mono flex-1" placeholder="name (a.b.c)" value={f.name} onChange={(e) => setField(idx, { name: e.target.value })} />
            <select aria-label={`field ${idx + 1} type`} className="field w-24" value={f.type || 'auto'} onChange={(e) => setField(idx, { type: e.target.value })}>
              {['auto', 'string', 'number', 'boolean', 'object', 'array'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
            <button className="btn-ghost px-2" aria-label="remove field" onClick={() => onChange(fields.filter((_, i) => i !== idx))}>
              ✕
            </button>
          </div>
          <ExpressionInput ariaLabel={`field ${idx + 1} value`} parse value={f.value} placeholder="value or {{trigger.field}}" onChange={(v) => setField(idx, { value: v })} />
        </div>
      ))}
      <button className="btn-ghost" onClick={() => onChange([...fields, { name: '', value: '', type: 'auto' }])}>
        + Add field
      </button>
    </div>
  );
}

/* ---------- dot-path helpers for config keys like "auth.type" ---------- */
export function getPath(obj: Record<string, any>, path: string): any {
  return path.split('.').reduce((acc: any, k) => (acc == null ? undefined : acc[k]), obj);
}

export function setPath(obj: Record<string, any>, path: string, value: unknown): Record<string, any> {
  const [head, ...rest] = path.split('.');
  const clone = { ...(obj || {}) };
  clone[head] = rest.length ? setPath(clone[head] || {}, rest.join('.'), value) : value;
  return clone;
}
