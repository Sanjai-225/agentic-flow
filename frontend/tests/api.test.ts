import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, ApiError, pollExecution } from '@/lib/api';
import { setSession } from '@/lib/auth';

import { execution } from './fixtures';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('pollExecution (frontend/backend execution sync)', () => {
  it('reports each backend state until a terminal status, then stops', async () => {
    const states = [execution('pending'), execution('running', [{ status: 'running' }]), execution('completed', [{ status: 'success' }])];
    const fetcher = vi.fn(async () => states.shift()!);
    const seen: string[] = [];
    const final = await pollExecution('exe_1', (d) => seen.push(d.status), { intervalMs: 1, fetcher });
    expect(seen).toEqual(['pending', 'running', 'completed']);
    expect(final?.status).toBe('completed');
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it('stops when aborted', async () => {
    const controller = new AbortController();
    const fetcher = vi.fn(async () => {
      controller.abort();
      return execution('running');
    });
    const final = await pollExecution('exe_1', () => {}, { intervalMs: 1, fetcher, signal: controller.signal });
    expect(final).toBeNull();
  });
});

describe('request()', () => {
  it('sends the bearer token and surfaces structured backend errors', async () => {
    setSession('tok123', 'a@b.c');
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: { message: 'Workflow cannot run until these problems are fixed.', issues: [{ message: 'x' }] } }), { status: 422 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.run('wf_1', {})).rejects.toMatchObject({ status: 422, message: 'Workflow cannot run until these problems are fixed.' });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer tok123');
  });

  it('reports an unreachable backend clearly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    const err = await api.listWorkflows().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toMatch(/Cannot reach the backend/);
  });
});
