'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import RequireAuth from '@/components/RequireAuth';
import { api } from '@/lib/api';
import { clearSession, getEmail } from '@/lib/auth';
import { EXECUTION_STATUS_STYLE } from '@/lib/status';
import type { WorkflowSummary } from '@/types/workflow';

function WorkflowList() {
  const router = useRouter();
  const [items, setItems] = useState<WorkflowSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => api.listWorkflows().then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <header className="mb-6 flex items-center gap-3">
        <div>
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">Workflows</h1>
          <p className="text-xs text-[var(--text-muted)]">{getEmail()}</p>
        </div>
        <div className="ml-auto flex gap-2">
          <button
            className="btn-ghost"
            onClick={() => {
              clearSession();
              router.replace('/login');
            }}
          >
            Sign out
          </button>
          <Link href="/workflows/new" className="btn-primary">
            + New workflow
          </Link>
        </div>
      </header>
      {error && <p className="mb-3 text-xs text-[var(--danger)]">{error}</p>}
      {items === null && !error && <p className="text-xs text-[var(--text-muted)]">Loading…</p>}
      {items?.length === 0 && (
        <div className="glass rounded-2xl p-8 text-center text-sm text-[var(--text-secondary)]">
          No workflows yet. <Link href="/workflows/new" className="text-[var(--accent)]">Create one</Link> manually or with the AI Designer.
        </div>
      )}
      <ul className="space-y-2">
        {items?.map((w) => {
          const st = w.last_execution_status ? EXECUTION_STATUS_STYLE[w.last_execution_status] : null;
          return (
            <li key={w.id} className="glass flex items-center gap-3 rounded-xl px-4 py-3">
              <Link href={`/workflows/${w.id}`} className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-[var(--text-primary)]">{w.name}</p>
                <p className="truncate text-[11px] text-[var(--text-muted)]">
                  v{w.version} · updated {w.updated_at ? new Date(w.updated_at).toLocaleString() : '—'}
                  {w.has_webhook ? ' · webhook enabled' : ''}
                </p>
              </Link>
              {st && (
                <span className="chip" style={{ color: st.color, background: 'rgba(255,255,255,0.05)' }}>
                  last run: {st.label}
                </span>
              )}
              <button
                className="btn-danger px-2 py-1"
                onClick={async () => {
                  if (!window.confirm(`Delete "${w.name}" and its execution history?`)) return;
                  await api.deleteWorkflow(w.id).catch((e) => setError(e.message));
                  refresh();
                }}
              >
                Delete
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function WorkflowsPage() {
  return (
    <RequireAuth>
      <WorkflowList />
    </RequireAuth>
  );
}
