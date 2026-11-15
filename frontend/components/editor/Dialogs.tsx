'use client';

import { useEffect, useState } from 'react';

import { api } from '@/lib/api';
import type { CredentialSummary, CredentialTestResult, CredentialTypeSpec } from '@/types/workflow';

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-label={title} onMouseDown={onClose}>
      <div className="glass-strong w-full max-w-lg rounded-2xl p-5" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h2>
          <button className="btn-ghost px-2" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function RunDialog({ initial, onRun, onClose }: { initial: unknown; onRun: (input: unknown) => void; onClose: () => void }) {
  const [text, setText] = useState(JSON.stringify(initial ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title="Run workflow" onClose={onClose}>
      <label className="label">Trigger payload (JSON)</label>
      <textarea aria-label="Run payload" rows={10} className="field-mono" value={text} onChange={(e) => setText(e.target.value)} />
      {error && <p className="mt-1 text-[11px] text-[var(--danger)]">{error}</p>}
      <p className="mt-2 text-[11px] text-[var(--text-muted)]">This payload becomes the trigger output, available as {'{{trigger.<field>}}'}. The run executes on the backend.</p>
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn-primary"
          onClick={() => {
            try {
              onRun(text.trim() ? JSON.parse(text) : {});
            } catch (e: any) {
              setError(`Invalid JSON: ${e.message}`);
            }
          }}
        >
          ▶ Run
        </button>
      </div>
    </Modal>
  );
}

const FIELD_LABEL: Record<string, string> = { token: 'Token', username: 'Username', password: 'Password', name: 'Header name', value: 'Header value', api_key: 'API key' };

function CredentialRow({ c, specs, onChanged, onError }: { c: CredentialSummary; specs: CredentialTypeSpec[]; onChanged: () => void; onError: (m: string) => void }) {
  const spec = specs.find((s) => s.type === c.type);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  const [data, setData] = useState<Record<string, string>>({});
  const [test, setTest] = useState<CredentialTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  return (
    <li className="space-y-1.5 rounded-md px-2 py-1.5 text-xs" style={{ background: 'var(--surface-sunken)' }} data-testid={`credential-${c.id}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0">
          <b className="text-[var(--text-primary)]">{c.name}</b> <span className="text-[var(--text-muted)]">{spec?.label || c.type}</span>{' '}
          {Object.entries(c.hints).map(([k, v]) => (
            <span key={k} className="font-mono text-[var(--text-muted)]">
              {FIELD_LABEL[k] || k}: {v}{' '}
            </span>
          ))}
        </span>
        <span className="flex flex-shrink-0 gap-1">
          {spec?.testable && (
            <button
              className="btn-ghost px-2 py-0.5"
              disabled={testing}
              onClick={async () => {
                setTesting(true);
                try {
                  setTest(await api.testCredential(c.id));
                } catch (e: any) {
                  setTest({ ok: false, message: e.message, models_available: [] });
                } finally {
                  setTesting(false);
                }
              }}
            >
              {testing ? 'Testing…' : 'Test'}
            </button>
          )}
          <button className="btn-ghost px-2 py-0.5" onClick={() => setEditing((v) => !v)}>
            Edit
          </button>
          <button className="btn-danger px-2 py-0.5" onClick={() => api.deleteCredential(c.id).then(onChanged).catch((e) => onError(e.message))}>
            Delete
          </button>
        </span>
      </div>
      {test && (
        <p className={`text-[11px] ${test.ok ? 'text-[var(--success)]' : 'text-[var(--danger)]'}`} role="status">
          {test.ok ? '✓' : '✗'} {test.message}
        </p>
      )}
      {editing && (
        <div className="space-y-1.5">
          <input aria-label="Edit credential name" className="field" value={name} onChange={(e) => setName(e.target.value)} />
          {(spec?.fields || []).map((f) => (
            <input
              key={f}
              aria-label={`New ${FIELD_LABEL[f] || f}`}
              className="field"
              type={spec?.secret_fields.includes(f) ? 'password' : 'text'}
              placeholder={`New ${FIELD_LABEL[f] || f} (leave empty to keep the stored value)`}
              value={data[f] || ''}
              onChange={(e) => setData({ ...data, [f]: e.target.value })}
              autoComplete="off"
            />
          ))}
          <button
            className="btn-primary"
            onClick={async () => {
              try {
                await api.updateCredential(c.id, { name, data: Object.fromEntries(Object.entries(data).filter(([, v]) => v)) });
                setEditing(false);
                setData({});
                setTest(null);
                onChanged();
              } catch (e: any) {
                onError(e.message);
              }
            }}
          >
            Save changes
          </button>
        </div>
      )}
    </li>
  );
}

export function CredentialsDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<CredentialSummary[]>([]);
  const [specs, setSpecs] = useState<CredentialTypeSpec[]>([]);
  const [type, setType] = useState('');
  const [name, setName] = useState('');
  const [data, setData] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const refresh = () => api.listCredentials().then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
    api
      .credentialTypeSpecs()
      .then((s) => {
        setSpecs(s);
        setType((t) => t || s[0]?.type || '');
      })
      .catch((e) => setError(e.message));
  }, []);
  const spec = specs.find((s) => s.type === type);
  return (
    <Modal title="Credentials" onClose={onClose}>
      <p className="mb-3 text-[11px] text-[var(--text-muted)]">
        Secrets are encrypted on the server and are never sent back to the browser (API keys are shown masked). Nodes reference credentials by ID; only you can use your credentials.
      </p>
      <ul className="mb-4 max-h-64 space-y-1 overflow-y-auto">
        {items.length === 0 && <li className="text-[11px] text-[var(--text-muted)]">No credentials yet.</li>}
        {items.map((c) => (
          <CredentialRow key={c.id} c={c} specs={specs} onChanged={refresh} onError={setError} />
        ))}
      </ul>
      <div className="space-y-2">
        <div className="flex gap-2">
          <select aria-label="Credential type" className="field w-48" value={type} onChange={(e) => (setType(e.target.value), setData({}))}>
            {specs.map((t) => (
              <option key={t.type} value={t.type}>
                {t.label}
              </option>
            ))}
          </select>
          <input aria-label="Credential name" className="field" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {(spec?.fields || []).map((f) => (
          <input
            key={f}
            aria-label={FIELD_LABEL[f] || f}
            className="field"
            type={spec?.secret_fields.includes(f) ? 'password' : 'text'}
            placeholder={FIELD_LABEL[f] || f}
            value={data[f] || ''}
            onChange={(e) => setData({ ...data, [f]: e.target.value })}
            autoComplete="off"
          />
        ))}
        {error && <p className="text-[11px] text-[var(--danger)]">{error}</p>}
        <button
          className="btn-primary"
          disabled={!type}
          onClick={async () => {
            try {
              setError(null);
              await api.createCredential(type, name || spec?.label || type, data);
              setName('');
              setData({});
              refresh();
            } catch (e: any) {
              setError(e.message);
            }
          }}
        >
          Add credential
        </button>
      </div>
    </Modal>
  );
}
