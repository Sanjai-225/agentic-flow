/*
 * Same-origin proxy to the FastAPI backend (used when NEXT_PUBLIC_API_URL is not set, e.g. on Vercel).
 * Forwards method, query, body and the Authorization header. It never injects secrets.
 */
import { NextRequest, NextResponse } from 'next/server';

import { BACKEND_NOT_CONFIGURED, resolveBackendUrl } from '@/lib/backendUrl';

export const dynamic = 'force-dynamic';

const FORWARDED_REQUEST_HEADERS = ['authorization', 'content-type', 'accept'];

async function proxy(request: NextRequest, { params }: { params: { path: string[] } }) {
  const backendBase = resolveBackendUrl();
  if (!backendBase) return NextResponse.json({ detail: BACKEND_NOT_CONFIGURED }, { status: 503 });
  const target = new URL(`/api/${params.path.map(encodeURIComponent).join('/')}`, backendBase);
  request.nextUrl.searchParams.forEach((value, key) => target.searchParams.append(key, value));

  const headers = new Headers();
  FORWARDED_REQUEST_HEADERS.forEach((h) => {
    const v = request.headers.get(h);
    if (v) headers.set(h, v);
  });

  try {
    const hasBody = !['GET', 'HEAD'].includes(request.method);
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: 'no-store',
    });
    const body = response.status === 204 ? null : await response.arrayBuffer();
    return new NextResponse(body, {
      status: response.status,
      headers: { 'content-type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (err: any) {
    return NextResponse.json({ detail: `Failed to reach backend at ${backendBase}: ${err?.message || 'unknown error'}` }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
