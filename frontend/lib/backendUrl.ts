/*
 * Server-side resolution of the FastAPI backend origin, used by the same-origin proxy (/api/*) and /health.
 *
 *   BACKEND_URL          server-only; preferred (e.g. https://<service>.onrender.com)
 *   NEXT_PUBLIC_API_URL  the browser's direct backend URL; reused when BACKEND_URL is not set
 *   local development    http://127.0.0.1:8000
 *
 * On Vercel (VERCEL=1) there is no localhost fallback: an unconfigured deployment reports a clear
 * configuration error instead of silently proxying to a development address.
 */

export const LOCAL_BACKEND_URL = 'http://127.0.0.1:8000';

export function resolveBackendUrl(env: Record<string, string | undefined> = process.env): string | null {
  const configured = (env.BACKEND_URL || env.NEXT_PUBLIC_API_URL || '').trim().replace(/\/+$/, '');
  if (configured) return configured;
  return env.VERCEL ? null : LOCAL_BACKEND_URL;
}

export const BACKEND_NOT_CONFIGURED =
  'Backend URL is not configured for this deployment. Set BACKEND_URL (or NEXT_PUBLIC_API_URL) in the Vercel project settings and redeploy.';
