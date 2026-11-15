#!/usr/bin/env node
/*
 * Pre-build environment guard (runs automatically before `npm run build`, locally and on Vercel).
 *
 * Fails the build when:
 *   - a NEXT_PUBLIC_* variable looks like a secret (it would be inlined into browser JavaScript);
 *   - on Vercel, the backend URL is missing, not https, or points at localhost (dev URLs must not leak).
 * Values are never printed - only variable names.
 *
 *   node scripts/check-env.mjs              # same check the build runs
 *   node scripts/check-env.mjs --production # apply the Vercel production rules locally
 */
import nextEnv from '@next/env';

const { loadEnvConfig } = nextEnv;
loadEnvConfig(process.cwd(), false); // same files `next build` loads (.env, .env.production, .env.local)

const env = process.env;
const strict = Boolean(env.VERCEL) || process.argv.includes('--production');
const target = env.VERCEL_ENV || (strict ? 'production (forced)' : 'local');
const errors = [];
const warnings = [];

const SECRET_NAME = /(SECRET|PASSWORD|PRIVATE|TOKEN|API_KEY|DATABASE|ENCRYPTION|CREDENTIAL|JWT)/i;
for (const name of Object.keys(env)) {
  if (name.startsWith('NEXT_PUBLIC_') && SECRET_NAME.test(name.slice('NEXT_PUBLIC_'.length))) {
    errors.push(`${name}: NEXT_PUBLIC_ variables are embedded in browser code; never put secrets in them.`);
  }
}

function checkUrl(name, required) {
  const raw = (env[name] || '').trim();
  if (!raw) {
    if (required) errors.push(`${name}: not set.`);
    return false;
  }
  let url;
  try {
    url = new URL(raw);
  } catch {
    errors.push(`${name}: not an absolute URL.`);
    return false;
  }
  if (['localhost', '127.0.0.1', '0.0.0.0', '[::1]'].includes(url.hostname)) {
    errors.push(`${name}: points at ${url.hostname}; use the deployed backend URL (https://<service>.onrender.com).`);
  } else if (url.protocol !== 'https:') {
    errors.push(`${name}: must use https.`);
  } else if (url.pathname !== '/' && url.pathname !== '') {
    warnings.push(`${name}: should be the origin only (no path); the client appends /api/... itself.`);
  }
  return true;
}

if (strict) {
  const direct = checkUrl('NEXT_PUBLIC_API_URL', false);
  const proxy = checkUrl('BACKEND_URL', false);
  if (!direct && !proxy) {
    errors.push('NEXT_PUBLIC_API_URL or BACKEND_URL must be set (see docs/PRODUCTION_DEPLOYMENT.md, "Vercel").');
  }
}

for (const w of warnings) console.warn(`[check-env] WARN ${w}`);
if (errors.length) {
  for (const e of errors) console.error(`[check-env] FAIL ${e}`);
  console.error(`[check-env] ${errors.length} problem(s) for target "${target}". Fix the Vercel/project environment and rebuild.`);
  process.exit(1);
}
console.log(`[check-env] OK (target: ${target}; mode: ${env.NEXT_PUBLIC_API_URL ? 'direct backend URL' : 'same-origin proxy'})`);
