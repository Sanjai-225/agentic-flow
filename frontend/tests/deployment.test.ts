import { describe, expect, it } from 'vitest';

import { LOCAL_BACKEND_URL, resolveBackendUrl } from '@/lib/backendUrl';

describe('resolveBackendUrl (server-side proxy target)', () => {
  it('prefers the server-only BACKEND_URL and strips trailing slashes', () => {
    expect(resolveBackendUrl({ BACKEND_URL: 'https://api.onrender.com/', NEXT_PUBLIC_API_URL: 'https://other.example' }))
      .toBe('https://api.onrender.com');
  });

  it('falls back to NEXT_PUBLIC_API_URL', () => {
    expect(resolveBackendUrl({ NEXT_PUBLIC_API_URL: 'https://api.onrender.com' })).toBe('https://api.onrender.com');
  });

  it('uses localhost only outside Vercel', () => {
    expect(resolveBackendUrl({})).toBe(LOCAL_BACKEND_URL);
    expect(resolveBackendUrl({ VERCEL: '1' })).toBeNull();
    expect(resolveBackendUrl({ VERCEL: '1', BACKEND_URL: '  ' })).toBeNull();
  });
});
