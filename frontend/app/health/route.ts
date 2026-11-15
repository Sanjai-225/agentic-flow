import { NextResponse } from 'next/server';

import { BACKEND_NOT_CONFIGURED, resolveBackendUrl } from '@/lib/backendUrl';

export const dynamic = 'force-dynamic';

/** Frontend health: reports whether this deployment can reach the backend's liveness endpoint. */
export async function GET() {
  const backendBase = resolveBackendUrl();
  if (!backendBase) return NextResponse.json({ status: 'unhealthy', detail: BACKEND_NOT_CONFIGURED }, { status: 503 });

  try {
    const response = await fetch(new URL('/health', backendBase), { cache: 'no-store' });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (err: any) {
    return NextResponse.json({ status: 'unhealthy', detail: err?.message || 'Unknown error' }, { status: 502 });
  }
}
