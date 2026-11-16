'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Loader2, Lock, Mail, Workflow } from 'lucide-react';

import { api } from '@/lib/api';
import { setSession } from '@/lib/auth';

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = mode === 'login' ? await api.login(email, password) : await api.register(email, password);
      setSession(res.access_token, res.user.email);
      router.replace('/workflows');
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-[420px] w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-600/20 blur-[120px]" />
      <form onSubmit={submit} className="glass-strong animate-fade-up relative w-full max-w-sm space-y-5 rounded-2xl p-7">
        <div className="flex flex-col items-center text-center">
          <span className="relative mb-4 flex h-11 w-11 items-center justify-center">
            <span className="absolute inset-0 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 opacity-70 blur-lg" />
            <span className="relative flex h-11 w-11 items-center justify-center rounded-xl border border-white/20 bg-gradient-to-br from-indigo-500 to-violet-600 shadow-[inset_0_1px_0_rgba(255,255,255,0.3)]">
              <Workflow size={20} className="text-white" />
            </span>
          </span>
          <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">Agentic Flow</h1>
          <p className="mt-1 text-xs text-[var(--text-muted)]">{mode === 'login' ? 'Sign in to your workspace' : 'Create an account'}</p>
        </div>
        <div>
          <label className="label" htmlFor="email">
            Email
          </label>
          <div className="relative">
            <Mail size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input id="email" type="email" required className="field py-2 pl-9" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="password">
            Password
          </label>
          <div className="relative">
            <Lock size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              id="password"
              type="password"
              required
              minLength={mode === 'register' ? 8 : 1}
              className="field py-2 pl-9"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>
        </div>
        {error && <p className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</p>}
        <button type="submit" className="btn-primary w-full py-2" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
        <button type="button" className="w-full text-xs text-[var(--text-muted)] transition-colors hover:text-indigo-300" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
          {mode === 'login' ? 'No account? Create one' : 'Have an account? Sign in'}
        </button>
      </form>
    </div>
  );
}
