'use client';

/* Hosted form for a Form Submission Trigger. Anonymous: never uses the editor session.
 * Client-side checks only improve UX - the backend validates every submission again. */

import { useEffect, useState } from 'react';

import { publicForms } from '@/lib/api';
import type { PublicForm, PublicFormField } from '@/types/workflow';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateField(field: PublicFormField, value: unknown): string | null {
  if (field.type === 'checkbox') return field.required && value !== true ? `${field.label} must be checked.` : null;
  const text = value === undefined || value === null ? '' : String(value).trim();
  if (!text) return field.required ? `${field.label} is required.` : null;
  if (field.type === 'email' && !EMAIL_RE.test(text)) return `${field.label} must be a valid email address.`;
  if (field.type === 'number') {
    const n = Number(text);
    if (!Number.isFinite(n)) return `${field.label} must be a number.`;
    if (field.min !== undefined && field.min !== null && n < field.min) return `${field.label} must be at least ${field.min}.`;
    if (field.max !== undefined && field.max !== null && n > field.max) return `${field.label} must be at most ${field.max}.`;
  }
  if (field.type === 'select' && !(field.options || []).includes(text)) return `${field.label} must be one of the listed options.`;
  if (field.max_length && text.length > field.max_length) return `${field.label} must be at most ${field.max_length} characters.`;
  if (field.min_length && text.length < field.min_length) return `${field.label} must be at least ${field.min_length} characters.`;
  return null;
}

export function PublicFormView({ formId }: { formId: string }) {
  const [form, setForm] = useState<PublicForm | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [honeypot, setHoneypot] = useState('');
  const [state, setState] = useState<'idle' | 'submitting' | 'done'>('idle');
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    publicForms
      .get(formId)
      .then((f) => alive && setForm(f))
      .catch((e) => alive && setLoadError(e.message || 'This form is not available.'));
    return () => {
      alive = false;
    };
  }, [formId]);

  if (loadError) {
    return (
      <Shell>
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">Form unavailable</h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">{loadError}</p>
      </Shell>
    );
  }
  if (!form) return <Shell><p className="text-sm text-[var(--text-muted)]">Loading form…</p></Shell>;
  if (state === 'done') {
    return (
      <Shell>
        <h1 className="text-lg font-semibold text-[var(--text-primary)]">{form.title}</h1>
        <p className="mt-3 text-sm text-[var(--success)]" role="status">{message}</p>
      </Shell>
    );
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    for (const f of form.fields) {
      const problem = validateField(f, values[f.key]);
      if (problem) found[f.key] = problem;
    }
    setErrors(found);
    setMessage(null);
    if (Object.keys(found).length) return;
    setState('submitting');
    const data: Record<string, unknown> = {};
    for (const f of form.fields) {
      const v = values[f.key];
      data[f.key] = f.type === 'checkbox' ? v === true : v === undefined ? '' : v;
    }
    const result = await publicForms.submit(formId, data, honeypot);
    if (result.ok) {
      setMessage(result.message);
      setState('done');
      return;
    }
    setErrors(result.errors || {});
    setMessage(result.message);
    setState('idle');
  };

  return (
    <Shell>
      <form onSubmit={submit} noValidate aria-label={form.title} className="space-y-4">
        <div>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">{form.title}</h1>
          {form.description && <p className="mt-1 whitespace-pre-line text-sm text-[var(--text-secondary)]">{form.description}</p>}
        </div>
        {form.fields.map((f) => (
          <FieldInput key={f.key} field={f} value={values[f.key]} error={errors[f.key]} onChange={(v) => setValues({ ...values, [f.key]: v })} />
        ))}
        {/* Honeypot: hidden from people, filled in by naive bots. */}
        <div aria-hidden="true" style={{ position: 'absolute', left: '-10000px', width: 1, height: 1, overflow: 'hidden' }}>
          <label>
            Leave this empty
            <input tabIndex={-1} autoComplete="off" name={form.honeypot_field} value={honeypot} onChange={(e) => setHoneypot(e.target.value)} />
          </label>
        </div>
        {errors._form && <p className="text-sm text-[var(--danger)]">{errors._form}</p>}
        {message && <p className="text-sm text-[var(--danger)]" role="alert">{message}</p>}
        <button type="submit" className="btn-primary w-full justify-center" disabled={state === 'submitting'}>
          {state === 'submitting' ? 'Sending…' : form.submit_label}
        </button>
      </form>
    </Shell>
  );
}

function FieldInput({ field, value, error, onChange }: { field: PublicFormField; value: unknown; error?: string; onChange: (v: unknown) => void }) {
  const id = `field-${field.key}`;
  const common = {
    id,
    name: field.key,
    'aria-invalid': Boolean(error),
    'aria-describedby': error ? `${id}-error` : undefined,
    className: 'field',
    placeholder: field.placeholder || undefined,
  };
  let control: React.ReactNode;
  if (field.type === 'checkbox') {
    control = (
      <label htmlFor={id} className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <input id={id} name={field.key} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)} />
        {field.label}
        {field.required && <span className="text-[var(--danger)]">*</span>}
      </label>
    );
  } else if (field.type === 'textarea') {
    control = <textarea {...common} rows={4} maxLength={field.max_length} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />;
  } else if (field.type === 'select') {
    control = (
      <select {...common} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select…</option>
        {(field.options || []).map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  } else {
    control = (
      <input
        {...common}
        type={field.type === 'email' ? 'email' : field.type === 'number' ? 'number' : 'text'}
        min={field.min}
        max={field.max}
        maxLength={field.max_length}
        value={String(value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return (
    <div>
      {field.type !== 'checkbox' && (
        <label htmlFor={id} className="label">
          {field.label}
          {field.required && <span className="text-[var(--danger)]"> *</span>}
        </label>
      )}
      {control}
      {field.help && <p className="mt-1 text-[11px] text-[var(--text-muted)]">{field.help}</p>}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-[11px] text-[var(--danger)]">
          {error}
        </p>
      )}
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-start justify-center p-4 sm:p-10">
      <div className="glass-strong w-full max-w-lg rounded-2xl p-6">{children}</div>
    </main>
  );
}
