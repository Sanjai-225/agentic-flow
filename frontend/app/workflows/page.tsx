'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ArrowUpRight, Clock, LogOut, Plus, Sparkles, Trash2, Webhook, Workflow } from 'lucide-react';

import RequireAuth from '@/components/RequireAuth';
import { api } from '@/lib/api';
import { clearSession, getEmail } from '@/lib/auth';
import { EXECUTION_STATUS_STYLE } from '@/lib/status';
import type { ExecutionStatus, WorkflowSummary } from '@/types/workflow';

/** Frosted semantic tones for the last-run badge (presentation only). */
const STATUS_TONE: Record<ExecutionStatus, { text: string; bg: string; border: string; dot: string; pulse: boolean }> = {
  completed: { text: '#34d399', bg: 'rgba(16,185,129,0.1)', border: 'rgba(16,185,129,0.25)', dot: '#10b981', pulse: false },
  failed: { text: '#fb7185', bg: 'rgba(244,63,94,0.1)', border: 'rgba(244,63,94,0.25)', dot: '#f43f5e', pulse: true },
  running: { text: '#67e8f9', bg: 'rgba(34,211,238,0.1)', border: 'rgba(34,211,238,0.25)', dot: '#22d3ee', pulse: true },
  pending: { text: '#a5b4fc', bg: 'rgba(99,102,241,0.1)', border: 'rgba(99,102,241,0.25)', dot: '#818cf8', pulse: true },
  paused: { text: '#fbbf24', bg: 'rgba(245,158,11,0.1)', border: 'rgba(245,158,11,0.25)', dot: '#f59e0b', pulse: false },
  cancelled: { text: '#94a3b8', bg: 'rgba(148,163,184,0.08)', border: 'rgba(148,163,184,0.2)', dot: '#64748b', pulse: false },
};

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return '—';
  const s = Math.round(diff / 1000);
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

function StatusBadge({ status }: { status: ExecutionStatus }) {
  const tone = STATUS_TONE[status];
  const label = EXECUTION_STATUS_STYLE[status]?.label ?? status;
  return (
    <span className="status-pill" style={{ color: tone.text, background: tone.bg, border: `1px solid ${tone.border}` }} title={`Last run: ${label}`}>
      <span className="relative flex h-1.5 w-1.5">
        {tone.pulse && <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ background: tone.dot }} />}
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full" style={{ background: tone.dot, boxShadow: `0 0 8px ${tone.dot}` }} />
      </span>
      {label}
    </span>
  );
}

function AppLogo() {
  return (
    <Link href="/workflows" className="group flex items-center gap-2.5">
      <span className="relative flex h-8 w-8 items-center justify-center">
        <span className="absolute inset-0 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 opacity-60 blur-md transition-opacity group-hover:opacity-90" />
        <span className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-white/20 bg-gradient-to-br from-indigo-500 to-violet-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.3)]">
          <Workflow size={16} className="text-white" strokeWidth={2.25} />
        </span>
      </span>
      <span className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">
        Agentic<span className="text-indigo-300">Flow</span>
      </span>
    </Link>
  );
}

function WorkflowList() {
  const router = useRouter();
  const [items, setItems] = useState<WorkflowSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => api.listWorkflows().then(setItems).catch((e) => setError(e.message));
  useEffect(() => {
    refresh();
  }, []);
  const email = getEmail() || '';
  const initial = (email[0] || '?').toUpperCase();

  return (
    <div className="min-h-screen">
      {/* Top navigation */}
      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#07080C]/70 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <AppLogo />
          <div className="ml-auto flex items-center gap-2">
            {email && (
              <span className="flex max-w-[200px] items-center gap-2 rounded-full border border-white/[0.08] bg-white/[0.03] py-1 pl-1 pr-3 sm:max-w-[260px]">
                <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-400 to-fuchsia-500 text-[11px] font-bold text-white">
                  {initial}
                </span>
                <span className="truncate text-xs text-[var(--text-secondary)]">{email}</span>
              </span>
            )}
            <button
              className="btn-icon"
              title="Sign out"
              aria-label="Sign out"
              onClick={() => {
                clearSession();
                router.replace('/login');
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 pt-10 sm:px-6">
        {/* Hero */}
        <section className="mb-8 flex flex-col gap-5 sm:flex-row sm:items-end">
          <div className="min-w-0">
            <p className="mb-2 inline-flex items-center gap-1.5 rounded-full border border-indigo-400/20 bg-indigo-500/10 px-2.5 py-0.5 text-[11px] font-medium text-indigo-300">
              <Sparkles size={12} /> Automation workspace
            </p>
            <h1 className="text-3xl font-bold tracking-tight text-[var(--text-primary)] sm:text-4xl">Workflows</h1>
            <p className="mt-1.5 text-sm text-[var(--text-muted)]">Design, automate, and monitor autonomous agent pipelines</p>
          </div>
          <Link href="/workflows/new" className="btn-primary rounded-full px-5 py-2.5 text-sm sm:ml-auto">
            <Plus size={16} strokeWidth={2.5} />
            New workflow
          </Link>
        </section>

        {error && (
          <p className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <AlertTriangle size={14} />
            {error}
          </p>
        )}

        {items === null && !error && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-[132px] animate-pulse rounded-xl border border-white/[0.06] bg-white/[0.025]" />
            ))}
            <p className="sr-only">Loading…</p>
          </div>
        )}

        {items?.length === 0 && (
          <div className="glass flex flex-col items-center rounded-2xl px-6 py-14 text-center">
            <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-indigo-400/30 bg-indigo-500/15 text-indigo-300 shadow-[0_0_30px_rgba(99,102,241,0.3)]">
              <Workflow size={22} />
            </span>
            <p className="text-sm font-semibold text-[var(--text-primary)]">No workflows yet</p>
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              <Link href="/workflows/new" className="text-indigo-300 hover:text-indigo-200">
                Create one
              </Link>{' '}
              manually or with the AI Designer.
            </p>
          </div>
        )}

        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items?.map((w, i) => (
            <li
              key={w.id}
              className="animate-fade-up group relative flex flex-col rounded-xl border border-white/[0.08] bg-white/[0.03] p-5 backdrop-blur-md transition-all duration-200 hover:-translate-y-0.5 hover:border-white/[0.16] hover:bg-white/[0.055] hover:shadow-[0_8px_30px_rgba(0,0,0,0.45)]"
              style={{ animationDelay: `${Math.min(i, 10) * 35}ms` }}
            >
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-indigo-400/25 bg-gradient-to-br from-indigo-500/20 to-violet-500/10 text-indigo-300">
                  <Workflow size={18} />
                </span>
                <Link href={`/workflows/${w.id}`} className="min-w-0 flex-1 after:absolute after:inset-0 after:rounded-xl after:content-['']">
                  <p className="truncate text-sm font-semibold tracking-tight text-[var(--text-primary)]">{w.name}</p>
                  <p className="mt-0.5 line-clamp-1 text-xs text-[var(--text-muted)]">{w.description || 'No description'}</p>
                </Link>
                <button
                  className="btn-icon relative z-10 -mr-1.5 -mt-1.5 opacity-70 hover:!bg-rose-500/10 hover:!text-rose-400 group-hover:opacity-100"
                  title="Delete workflow"
                  aria-label={`Delete ${w.name}`}
                  onClick={async () => {
                    if (!window.confirm(`Delete "${w.name}" and its execution history?`)) return;
                    await api.deleteWorkflow(w.id).catch((e) => setError(e.message));
                    refresh();
                  }}
                >
                  <Trash2 size={15} />
                </button>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                {w.last_execution_status && <StatusBadge status={w.last_execution_status} />}
                {w.active && (
                  <span className="status-pill border border-cyan-400/20 bg-cyan-500/10 text-cyan-300">
                    <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 shadow-[0_0_8px_#22d3ee]" />
                    Active
                  </span>
                )}
                {w.has_webhook && (
                  <span className="status-pill border border-white/[0.08] bg-white/[0.04] normal-case tracking-normal text-[var(--text-secondary)]" title="webhook enabled">
                    <Webhook size={11} />
                    webhook enabled
                  </span>
                )}
              </div>

              <div className="mt-auto flex items-center gap-2 pt-4 text-[11px] text-[var(--text-muted)]">
                <span className="mono-badge">v{w.version}</span>
                <span className="flex items-center gap-1" title={w.updated_at ? new Date(w.updated_at).toLocaleString() : undefined}>
                  <Clock size={12} />
                  updated {relativeTime(w.updated_at)}
                </span>
                <ArrowUpRight size={14} className="ml-auto text-[var(--text-muted)] opacity-0 transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-indigo-300 group-hover:opacity-100" />
              </div>
            </li>
          ))}
        </ul>
      </main>
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
