'use client';

import { useEffect, useState } from 'react';

import { api } from '@/lib/api';
import type { CredentialSummary } from '@/types/workflow';

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

const TYPE_FIELDS: Record<string, { key: string; label: string; secret: boolean }[]> = {
  http_bearer: [{ key: 'token', label: 'Token', secret: true }],
  http_basic: [
    { key: 'username', label: 'Username', secret: false },
    { key: 'password', label: 'Password', secret: true },
  ],
  http_header: [
    { key: 'name', label: 'Header name', secret: false },
    { key: 'value', label: 'Header value', secret: true },
  ],
};

export function CredentialsDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<CredentialSummary[]>([]);
  const [type, setType] = useState('http_bearer');
  const [name, setName] = useState('');
  const [data, setData] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const refresh = () => api.listCredentials().then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
  }, []);
  return (
    <Modal title="Credentials" onClose={onClose}>
      <p className="mb-3 text-[11px] text-[var(--text-muted)]">Secrets are encrypted on the server and are never sent back to the browser. Nodes reference credentials by ID.</p>
      <ul className="mb-4 space-y-1">
        {items.length === 0 && <li className="text-[11px] text-[var(--text-muted)]">No credentials yet.</li>}
        {items.map((c) => (
          <li key={c.id} className="flex items-center justify-between rounded-md px-2 py-1.5 text-xs" style={{ background: 'var(--surface-sunken)' }}>
            <span>
              <b className="text-[var(--text-primary)]">{c.name}</b> <span className="text-[var(--text-muted)]">{c.type}</span>{' '}
              {Object.entries(c.hints).map(([k, v]) => (
                <span key={k} className="text-[var(--text-muted)]">
                  {k}={v}{' '}
                </span>
              ))}
            </span>
            <button className="btn-danger px-2 py-0.5" onClick={() => api.deleteCredential(c.id).then(refresh).catch((e) => setError(e.message))}>
              Delete
            </button>
          </li>
        ))}
      </ul>
      <div className="space-y-2">
        <div className="flex gap-2">
          <select aria-label="Credential type" className="field w-40" value={type} onChange={(e) => (setType(e.target.value), setData({}))}>
            {Object.keys(TYPE_FIELDS).map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <input aria-label="Credential name" className="field" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {TYPE_FIELDS[type].map((f) => (
          <input
            key={f.key}
            aria-label={f.label}
            className="field"
            type={f.secret ? 'password' : 'text'}
            placeholder={f.label}
            value={data[f.key] || ''}
            onChange={(e) => setData({ ...data, [f.key]: e.target.value })}
            autoComplete="off"
          />
        ))}
        {error && <p className="text-[11px] text-[var(--danger)]">{error}</p>}
        <button
          className="btn-primary"
          onClick={async () => {
            try {
              setError(null);
              await api.createCredential(type, name || type, data);
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
