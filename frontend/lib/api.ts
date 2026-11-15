/* Typed client for the Agentic Flow backend. All execution state shown in the UI comes from here. */

import { clearSession, getToken } from '@/lib/auth';
import type {
  CredentialSummary,
  ExecutionDetail,
  ExecutionSummary,
  RegistryCatalogResponse,
  ValidationResult,
  WorkflowDefinition,
  WorkflowRecord,
  WorkflowResponse,
  WorkflowSummary,
} from '@/types/workflow';
import { TERMINAL_STATUSES } from '@/types/workflow';

const API_BASE_URL =
  typeof process.env.NEXT_PUBLIC_API_URL === 'string' && process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL.replace(/\/+$/, '')
    : '';

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, message: string, detail?: any) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFromDetail(detail: any, fallback: string): string {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (typeof detail.message === 'string') return detail.message;
  if (Array.isArray(detail)) {
    return detail.map((d: any) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  }
  return fallback;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch (err: any) {
    throw new ApiError(0, `Cannot reach the backend${API_BASE_URL ? ` at ${API_BASE_URL}` : ''}. Is it running? (${err?.message || 'network error'})`);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    if (res.status === 401 && typeof window !== 'undefined' && !path.startsWith('/api/auth/')) {
      clearSession();
      if (!window.location.pathname.startsWith('/login')) window.location.href = '/login';
    }
    const detail = body?.detail ?? body;
    throw new ApiError(res.status, messageFromDetail(detail, `Request failed (${res.status})`), detail);
  }
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  register: (email: string, password: string) =>
    request<{ access_token: string; user: { id: string; email: string } }>('/api/auth/register', {
      method: 'POST',
      body: json({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string; user: { id: string; email: string } }>('/api/auth/login', {
      method: 'POST',
      body: json({ email, password }),
    }),
  me: () => request<{ id: string; email: string }>('/api/auth/me'),

  registry: () => request<RegistryCatalogResponse>('/api/registry/nodes'),
  generate: (prompt: string) =>
    request<WorkflowResponse>('/api/workflows/generate', { method: 'POST', body: json({ prompt }) }),

  listWorkflows: () => request<WorkflowSummary[]>('/api/workflows'),
  getWorkflow: (id: string) => request<WorkflowRecord>(`/api/workflows/${id}`),
  createWorkflow: (definition: WorkflowDefinition) =>
    request<WorkflowRecord>('/api/workflows', { method: 'POST', body: json({ definition }) }),
  updateWorkflow: (id: string, definition: WorkflowDefinition) =>
    request<WorkflowRecord>(`/api/workflows/${id}`, { method: 'PUT', body: json({ definition }) }),
  deleteWorkflow: (id: string) => request<void>(`/api/workflows/${id}`, { method: 'DELETE' }),
  validate: (definition: WorkflowDefinition) =>
    request<ValidationResult>('/api/workflows/validate', { method: 'POST', body: json({ definition }) }),
  run: (id: string, input: unknown) =>
    request<{ execution_id: string; status: string }>(`/api/workflows/${id}/run`, {
      method: 'POST',
      body: json({ input }),
    }),
  listExecutions: (id: string) => request<ExecutionSummary[]>(`/api/workflows/${id}/executions`),
  getExecution: (id: string) => request<ExecutionDetail>(`/api/executions/${id}`),
  cancelExecution: (id: string) => request<{ status: string }>(`/api/executions/${id}/cancel`, { method: 'POST' }),
  createWebhook: (id: string) =>
    request<{ token: string; url: string; method: string }>(`/api/workflows/${id}/webhook`, { method: 'POST' }),

  listCredentials: () => request<CredentialSummary[]>('/api/credentials'),
  createCredential: (type: string, name: string, data: Record<string, string>) =>
    request<CredentialSummary>('/api/credentials', { method: 'POST', body: json({ type, name, data }) }),
  deleteCredential: (id: string) => request<void>(`/api/credentials/${id}`, { method: 'DELETE' }),
};

/**
 * Poll an execution until it reaches a terminal status. Every update comes from the backend;
 * nothing is simulated client-side. Returns the final detail, or null if aborted.
 */
export async function pollExecution(
  executionId: string,
  onUpdate: (detail: ExecutionDetail) => void,
  opts: { intervalMs?: number; signal?: AbortSignal; fetcher?: (id: string) => Promise<ExecutionDetail> } = {},
): Promise<ExecutionDetail | null> {
  const interval = opts.intervalMs ?? 750;
  const fetcher = opts.fetcher ?? api.getExecution;
  for (;;) {
    if (opts.signal?.aborted) return null;
    const detail = await fetcher(executionId);
    if (opts.signal?.aborted) return null;
    onUpdate(detail);
    if (TERMINAL_STATUSES.includes(detail.status)) return detail;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
}
