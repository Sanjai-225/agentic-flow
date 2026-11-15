# Deployment readiness report: Vercel + Render + Supabase

_Date: 2026-11-15 · Branch: `testing` · Scope: production-readiness and deployment automation for the
Milestone 2 application. **Nothing has been deployed.** No platform project was created and no hosting was
purchased. Every PASS below refers to local validation or to a static check of the configuration files.
"Configured" means a configuration file exists; it does not mean a platform is set up._

> **Free-tier revision (latest).** At the owner's request the package now targets **Render Free + Supabase
> Free + Vercel Hobby**:
> - `render.yaml` uses `plan: free`, `DB_AUTO_MIGRATE=true` (the additive migrations run at startup, so there
>   is no manual migration step) and a smaller pool (3 + 2).
> - The Dockerfile and `.dockerignore` were removed; no Docker, Redis, separate worker or paid add-on is used.
> - Free-tier limits are explained in `docs/PRODUCTION_DEPLOYMENT.md`: backend sleep, Schedule Triggers not
>   firing while asleep, interrupted runs, Supabase pausing, no free backups.
> - Rows below that mention `starter`, `DB_AUTO_MIGRATE=false` or Docker describe the earlier paid-tier
>   variant. The `deploy_migrations.py` safety script remains available for manual use.
> - No further local tests were run for this revision, per the owner's instruction. Only the static config
>   check was re-run: 41/41 PASS, including the official Render schema.

Status legend:
- **PASS**: verified here
- **FAIL**: verified broken
- **PARTIAL**: partly verified
- **MANUAL ACTION REQUIRED**: a dashboard step only you can do
- **NOT TESTED**: could not be verified in this environment

---

## 1. Final architecture

```
Browser ──https──► Vercel (Next.js 14: editor, /login, /workflows, hosted /forms/<id>)
   │                  └─ /health and /api/* proxy (server-side; used by preview deployments)
   └──https (Bearer JWT, CORS)──► Render web service "agentic-flow-api" (1 instance, uvicorn --workers 1)
                                     ├─ FastAPI REST API (auth, workflows, executions, credentials, AI)
                                     ├─ public ingress: /api/webhooks/{id}/{token}, /api/public/forms/{id}
                                     ├─ ExecutionManager: in-process asyncio execution worker
                                     └─ Scheduler loop: DB-driven, unique-claim occurrences
                                            │
                                            └──TLS, session pooler :5432──► Supabase PostgreSQL
                                                                              (RLS on, Data API blocked)
```

Audit facts (taken from the code):
- **Frontend.** Lives in `frontend/`. Next.js App Router. Build is `next build`, start is `next start`.
  Browser API calls go to `NEXT_PUBLIC_API_URL` (`lib/api.ts`), or same-origin through
  `app/api/[...path]/route.ts`.
- **Backend.** Lives in `backend/`. Entry point is `app.main:app`. Lifespan steps:
  1. configuration checks
  2. migrate (`DB_AUTO_MIGRATE`), or verify the schema is current
  3. reconcile interrupted executions
  4. start the scheduler
- **Database layer.** SQLAlchemy 2 async plus Alembic. Tables use string ids (`new_id()`, not native UUIDs),
  `JSON` columns, `DateTime(timezone=True)`, foreign keys with `ON DELETE CASCADE`, and unique constraints.
- **Background work.** No queue. Executions run as asyncio tasks in the API process; the scheduler polls the
  database every 5 s.
- **Auth.** Bearer JWT (HS256) plus argon2 password hashes. No cookies.
- **File storage.** None. No uploads; everything is in the database.
- **Health.** `/health` (liveness) existed. `/health/ready` was added.

## 2. Requirement matrix

| # | Requirement | Status | Evidence / note |
|---|---|---|---|
| 1 | Architecture audit from code | PASS | §1 |
| 2a | SQLAlchemy / driver compatibility (asyncpg 0.32.0 app, psycopg 3.3.9 Alembic) | PARTIAL | Installed, imported, URL normalisation unit-tested. **No live PostgreSQL connection made** (see 2f). |
| 2b | Single `DATABASE_URL` for SQLite (dev) and PostgreSQL (prod) | PASS | `app/db/url.py`; tests in `tests/test_deployment.py` |
| 2c | Supabase connection mode decided (session pooler for Render) | PASS (research) | Render has no outbound IPv6; Supabase direct host is IPv6 unless the paid IPv4 add-on is bought. Session pooler (5432) is IPv4 on all plans. |
| 2d | Pooling and connection recovery | PASS (code) / NOT TESTED (live) | pool_size 5 + overflow 5, `pool_pre_ping`, recycle 300 s, connect/command timeouts; transaction-pooler mode disables prepared-statement caches |
| 2e | Migrations compatible with PostgreSQL | PARTIAL | `--sql` offline rendering available for PostgreSQL; executed only on SQLite. Live PostgreSQL run **NOT TESTED**. |
| 2f | Real PostgreSQL test database (migrations, persistence, concurrency, JSON, timestamps, FKs) | **NOT TESTED** | Starting the downloaded PostgreSQL 17 binaries was blocked by this session's permission policy. The suite can target PostgreSQL with `TEST_DATABASE_URL` (see §9). |
| 2g | Supabase Data API exposure | PASS (code) / NOT TESTED (live) | Migration `0003` enables RLS on all 12 tables (no-op on SQLite); a test enforces coverage of new tables; `check_database.py` verifies it live |
| 2h | Safe migration procedure, no automatic destructive migrations | PASS | `deploy_migrations.py`: dry run by default, typed confirmation, refuses destructive and unknown revisions; production `DB_AUTO_MIGRATE=false` + startup schema guard (tested) |
| 2i | SQLite → PostgreSQL data transfer procedure | PARTIAL | `transfer_sqlite_to_postgres.py` verified SQLite→SQLite (refuses non-empty target and stale source; row counts match on a copy of the dev DB). PostgreSQL-specific steps (sequence reset, UTC session) **NOT TESTED**. |
| 3a | `render.yaml` valid against Render's official schema | PASS | `check_deployment_config.py --schemas`: 0 errors (it caught `generation: off` parsing as YAML boolean, now fixed) |
| 3b | Build/start/health/single instance/secrets in Blueprint | PASS (static) | Exact start command run locally (see §8) |
| 3c | No duplicate scheduler execution; restart safety | PASS (tests) | Unique `(schedule_id, scheduled_for)` claim; existing two-scheduler and restart tests pass on SQLite; PostgreSQL IntegrityError path **NOT TESTED** live |
| 3d | Render deploy actually works | NOT TESTED | Requires your Render account |
| 4a | Vercel config (`vercel.json`, root dir, framework) | PASS (static) | Valid against official Vercel schema; root directory is a dashboard setting (MANUAL) |
| 4b | No backend secrets in `NEXT_PUBLIC_*`; no localhost in production | PASS | `scripts/check-env.mjs` runs as `prebuild`; tested in local / forced-production / proxy / secret-name cases |
| 4c | Vercel deploy actually works | NOT TESTED | Requires your Vercel account |
| 5 | URL strategy (no hard-coded production URLs) | PASS | `PUBLIC_BASE_URL` ← `RENDER_EXTERNAL_URL`; `PUBLIC_APP_URL`/`CORS_ORIGINS` prompted; frontend URL from env only; previews via proxy |
| 6 | Env examples and full variable reference | PASS | `backend/.env.example`, `frontend/.env.example`, `PRODUCTION_DEPLOYMENT.md` §7; checker confirms every variable the code reads is documented |
| 7 | Dockerfile + .dockerignore | PARTIAL | Written (non-root, HEALTHCHECK, exec CMD, single worker); statically checked. **`docker build` NOT TESTED** (Docker not installed). Render uses the native Python runtime, so Docker is optional. |
| 8 | Deployment scripts | PASS | 8 scripts, each executed (§8) |
| 9 | Security review | PASS with limitations | §6 |
| 10a | Backend tests | PASS | 414 passed, 13 skipped (live tests) |
| 10b | Frontend tests / typecheck / lint / build | PASS | 62 passed; typecheck clean; lint: 1 pre-existing font warning; production build OK |
| 10c | Backend production startup | PASS (SQLite, production-like) / NOT TESTED (PostgreSQL) | §8 |
| 11 | Deployment guide | PASS | `docs/PRODUCTION_DEPLOYMENT.md` |
| 12 | This report | PASS | |

## 3. Files created or modified

**New:**

| File | Purpose |
|---|---|
| `render.yaml` | Render Blueprint (one web service) |
| `frontend/vercel.json` | Pins the Next.js framework, `npm ci` and `npm run build` |
| `frontend/scripts/check-env.mjs` | Prebuild guard against localhost URLs and secret-like public variables |
| `frontend/lib/backendUrl.ts` | Server-side backend URL resolution; no localhost fallback on Vercel |
| `frontend/tests/deployment.test.ts` | Tests for `backendUrl.ts` |
| `backend/Dockerfile`, `backend/.dockerignore` | Optional container image |
| `backend/app/db/url.py` | `DATABASE_URL` parsing: drivers, sslmode, pooler, redaction |
| `backend/app/core/production.py` | Production configuration rules |
| `backend/alembic/versions/0003_postgres_row_level_security.py` | RLS on all application tables (PostgreSQL only) |
| `backend/scripts/` | `_deploy_common.py`, `validate_environment.py`, `check_database.py`, `deploy_migrations.py`, `check_deployment_config.py`, `verify_production.py`, `smoke_test_deployment.py`, `generate_secrets.py`, `transfer_sqlite_to_postgres.py` |
| `backend/tests/test_deployment.py` | Deployment tests |
| `docs/PRODUCTION_DEPLOYMENT.md`, `docs/DEPLOYMENT_READINESS_REPORT.md` | Guide and this report |

**Modified:**

| File | Change |
|---|---|
| `backend/app/main.py` | Production config gate; schema guard when auto-migrate is off; CORS without the hard-coded `*.vercel.app` regex and without credentials |
| `backend/app/core/config.py` | `CORS_ORIGIN_REGEX`; `DB_POOL_*`; `PUBLIC_BASE_URL` ← `RENDER_EXTERNAL_URL`; `AGENTIC_FLOW_NO_DOTENV` |
| `backend/app/db/session.py` | Engine options per backend; `migration_status`; `ensure_schema_current` (allows a newer schema for rollbacks); `%` escaping for Alembic |
| `backend/alembic/env.py` | `%` escaping |
| `backend/app/api/workflow.py` | `/health/ready` |
| `backend/app/engine/scheduler.py` | `running` property |
| `backend/requirements.txt` | asyncpg, psycopg[binary] |
| `backend/requirements-dev.txt` | PyYAML |
| `backend/tests/conftest.py` | Optional `TEST_DATABASE_URL` (the database name must contain "test") |
| `backend/.env.example` | Rewritten: every variable the code reads |
| `backend/main.py` | Docstring |
| `frontend/next.config.mjs` | Security headers; `poweredByHeader: false` |
| `frontend/package.json` | `prebuild` and `check-env` scripts |
| `frontend/app/health/route.ts`, `frontend/app/api/health/route.ts`, `frontend/app/api/[...path]/route.ts` | Use `backendUrl.ts` |
| `frontend/.env.local.example` → `frontend/.env.example` | Renamed |
| `README.md` | References the renamed file |

**Milestone 2 behaviour is unchanged.** All 413 pre-existing backend tests and 59 frontend tests still pass.

## 4. Database: PostgreSQL / Supabase

| Area | Finding |
|---|---|
| Drivers | App uses `postgresql+asyncpg`; Alembic uses `postgresql+psycopg`. `postgres://`, `postgresql://` and explicit-driver URLs are all accepted. |
| TLS | `sslmode` is translated for asyncpg and defaults to `require` for non-local hosts. Production refuses `disable`/`allow`/`prefer`. |
| JSON | Columns use generic `JSON` (PostgreSQL `json`). No JSON operators, equality, DISTINCT or GROUP BY on JSON columns were found in the code, so `json` vs `jsonb` makes no functional difference. Kept as is to avoid a type-changing migration. |
| IDs | String primary keys with prefixes (`usr_`, `wf_`, ...), generated in Python. No native UUID columns, so nothing is dialect-specific. Integer autoincrement ids (versions, node executions, logs, usage, occurrences) become `SERIAL`/identity. |
| Timestamps | `timestamptz`. Code already normalises naive values from SQLite (`_aware`). |
| Lengths | `VARCHAR(n)` is enforced on PostgreSQL but not on SQLite. **Risk:** a value longer than its column fails only on PostgreSQL. Covered only once the suite runs against PostgreSQL (§9). |
| Concurrency | Schedule claims rely on the unique constraint plus `IntegrityError` → rollback (`scheduler.py`). This is correct for PostgreSQL's aborted-transaction semantics, but not exercised live. |
| Pooling | `pool_size + max_overflow = 10` per instance, below the session pooler's per-project client limits on Supabase plans. Lower them on the smallest plans if you see pool-limit errors. |
| Supabase Auth | Not used. FastAPI auth is kept. |

## 5. Platform configuration

**Render** (`render.yaml`):
- Service: `web`, `runtime: python`, `rootDir: backend`, `plan: starter`, `numInstances: 1`,
  `healthCheckPath: /health`, `maxShutdownDelaySeconds: 30`, `previews.generation: "off"`.
- Deploys only for backend changes (`buildFilter`); `autoDeployTrigger: commit`.
- Build: `pip install --upgrade pip && pip install -r requirements.txt`.
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips "*" --timeout-graceful-shutdown 25 --no-server-header`.
- Fixed values: `PYTHON_VERSION=3.13`, `APP_ENV=production`, `DB_AUTO_MIGRATE=false`, `DB_POOL_*`,
  `AI_ALLOW_PLATFORM_KEYS=false`, `HTTP_ALLOW_PRIVATE_NETWORKS=false`, `SCHEDULER_ENABLED=true`.
- Generated: `JWT_SECRET`.
- Prompted: `DATABASE_URL`, `CREDENTIALS_ENCRYPTION_KEY`, `PUBLIC_APP_URL`, `CORS_ORIGINS`, `GEMINI_API_KEY`.

**Vercel:**
- Root directory: `frontend` (MANUAL).
- `vercel.json`: `framework: nextjs`, `installCommand: npm ci`, `buildCommand: npm run build`.
- No rewrites are needed.
- Production uses direct browser→Render calls (`NEXT_PUBLIC_API_URL`). Previews use the server-side proxy
  (`BACKEND_URL`).

**Redis decision: not introduced.**
- **Nothing needs it.** There is no queue or broker in the code. Executions run in-process; the scheduler is
  database-driven and duplicate-safe through database constraints; sessions are stateless JWTs.
- **The cost of skipping it** is the single-instance constraint:
  - the in-memory rate limiter is per process
  - cancelling a run only works inside the process that is running it
  - executions are not durable across restarts
- **Scaling to more than one instance** needs a shared queue and shared rate-limit store (Redis or database
  based). That is the existing Milestone 4 hardening item, not a deployment-configuration change.

**Worker and scheduler:** no separate Render worker or cron service. Moving them out would need code changes
(a durable queue), and two scheduler loops would buy nothing because the database claim already serialises
them.

## 6. Security review

| Area | Result |
|---|---|
| Authentication / JWT | HS256 with argon2 password hashes. Production requires `JWT_SECRET` ≥ 32 chars; Render generates 256 bits. Rotation logs users out (documented). |
| Encryption key stability | Production refuses to start without a valid Fernet `CREDENTIALS_ENCRYPTION_KEY`. It is prompted rather than generated so a Blueprint re-creation cannot silently replace it. Backup and never-rotate are documented. |
| Credential encryption / redaction | Unchanged from Milestone 2 (Fernet, masked hints, scrubbed traces/logs). The production-like run log contains no secret-like strings. |
| Tenant isolation | Unchanged (user_id filters, existing tests); also checked by the smoke test (other user gets 404). |
| **CORS (fixed)** | Before: `allow_origin_regex=https://.*\.vercel\.app` with `allow_credentials=True` was always on, so any site on vercel.app was a trusted origin. Now origins come only from `CORS_ORIGINS` / an optional anchored `CORS_ORIGIN_REGEX`; credentials are off (Bearer tokens); production rejects `*`, localhost and over-broad regexes. Tested. |
| SSRF | HTTP node and agent `http_get` block private networks. Production refuses `HTTP_ALLOW_PRIVATE_NETWORKS=true`. |
| Webhooks / forms | Hashed webhook tokens, unguessable form ids, body caps, honeypot, per-IP rate limits. `--proxy-headers` makes rate limits use the real client IP behind Render's proxy. |
| Supabase Data API | RLS on every table (migration 0003); `check_database.py` verifies it. |
| Database transport | TLS required for hosted databases (enforced). |
| Error handling / debug | No `debug=True`, no `--reload` in production; `--no-server-header`; readiness reports error classes, not messages or hosts. |
| Frontend headers | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`; `X-Powered-By` removed. |
| Restarts | No saved data is lost (everything is in PostgreSQL). Schedules cannot double-fire. |

Remaining limitations, accepted and documented:
1. **In-flight runs during a deploy.** Runs still executing during a restart or deploy are marked failed
   ("interrupted"); there is no resume (Milestone 4).
   - During Render's zero-downtime overlap, the *new* instance's startup reconciliation can mark a run that
     the *old* instance is still finishing as failed.
   - Avoid deploying while important long runs are active.
2. **Single instance only.** Rate limits and cancellation are in-process. Do not scale `numInstances`
   beyond 1.
3. **API docs are public.** `/docs` and `/openapi.json` are reachable without login. They expose no data,
   but you may want to disable them in production.
4. **Rate limiting is per process** and resets on restart.
5. **Backups depend on your Supabase plan.** Run `pg_dump` before migrations (documented).

## 7. Manual dashboard settings (cannot be automated here)

| Platform | Action |
|---|---|
| Supabase | Create the project (region, DB password); copy the session pooler URI; optionally disable the Data API; check the backup plan. |
| Render | Connect GitHub; create the Blueprint from the repo; enter the 5 prompted values; confirm `plan: starter` (paid) or change it; copy the service URL; custom domain (optional). |
| Vercel | Import the repo; **Root Directory = `frontend`**; set `NEXT_PUBLIC_API_URL` and `BACKEND_URL` (Production) and `BACKEND_URL` (Preview); deploy; copy the URL. |
| Cross-wiring | Vercel URL → Render `CORS_ORIGINS` and `PUBLIC_APP_URL`; Render URL → Vercel variables; redeploy both. |
| Git | Merge to `main` and push (render.yaml deploys `main`). Not done: no commit or push was made. |

## 8. Local validation results (this machine)

| Check | Result |
|---|---|
| `pytest -q` (backend) | 414 passed, 13 skipped (live, opt-in) |
| `ruff check app tests alembic/env.py scripts` | clean |
| `vitest` / `tsc` / `next lint` / `next build` | 62 passed / clean / 1 pre-existing warning / OK |
| `check_deployment_config.py --schemas` | 43/43 PASS, including the official Render and Vercel schemas |
| `APP_ENV=production` with dev-style config | refuses to start, lists `DATABASE_URL`, `JWT_SECRET`, `CREDENTIALS_ENCRYPTION_KEY` by name; no DB file created |
| `DB_AUTO_MIGRATE=false`, empty DB | refuses to start with "schema is not at the latest migration" |
| `deploy_migrations.py` | dry run lists 0001–0003; non-interactive apply refused without `--yes`; apply succeeds; re-run "nothing to apply" |
| `check_database.py --write-probe` | 5/5 PASS (SQLite) |
| Production-like stack | Render start command (uvicorn flags) + `next build`/`next start`, migrated DB, auto-migrate off |
| `verify_production.py` on that stack | 17 PASS, 2 expected FAIL (http on localhost), 1 WARN (APP_ENV=staging) |
| `smoke_test_deployment.py --with-schedule` | 12/12 PASS (manual run, webhook via auto-derived public URL, hosted form page + validation, real scheduled run, tenant isolation, cleanup) |
| `transfer_sqlite_to_postgres.py` | SQLite→SQLite on a dev DB copy: all row counts match; refuses a non-empty target and a stale source |

Local-only note: on Windows, the `"*"` argument of `--forwarded-allow-ips` is glob-expanded when launched
from Git Bash, so the local run passed `FORWARDED_ALLOW_IPS='*'` (uvicorn's equivalent environment
variable). Render runs the command in a Linux shell, where the quoted `"*"` stays literal.

## 9. Remaining blockers

1. **Real PostgreSQL validation (NOT TESTED).** This is the main open item. To close it, run against any
   disposable PostgreSQL 15+ database (a separate free Supabase project, or a local server):
   ```powershell
   cd D:\Oneinfer\Project\agentic-flow\backend
   $env:TEST_DATABASE_URL = "postgresql://postgres:<pw>@localhost:5432/agentic_flow_test"   # name must contain 'test'
   python -m pytest -q
   python scripts\deploy_migrations.py --sql          # with DATABASE_URL set to the same database
   python scripts\check_database.py --write-probe
   Remove-Item Env:TEST_DATABASE_URL
   ```
   Expect length-limit or dialect issues, if any, to show up here first.
2. **`docker build` (NOT TESTED).** Only relevant if you deploy the container instead of Render's Python
   runtime.
3. **Platform deployment (NOT TESTED).** It needs your accounts; follow `PRODUCTION_DEPLOYMENT.md`, then run
   `verify_production.py` and `smoke_test_deployment.py` against the real URLs.

## 10. Exact deployment sequence

1. Merge `testing` → `main` and push. The deployment files must be on `main`.
2. **Supabase:** create the project. Copy the session pooler URI.
3. Locally:
   - `check_database.py --prompt-url --write-probe`
   - `deploy_migrations.py --prompt-url --apply` (**approve the migrations**)
   - `check_database.py --prompt-url` (expect RLS on, migrations at head)
4. Locally: `generate_secrets.py`.
5. **Render:** create a Blueprint from the repo. Enter `DATABASE_URL`, `CREDENTIALS_ENCRYPTION_KEY`,
   `GEMINI_API_KEY`, plus temporary `PUBLIC_APP_URL`/`CORS_ORIGINS`. Apply. Copy the service URL.
6. **Vercel:** import the repo with Root Directory `frontend`. Set `NEXT_PUBLIC_API_URL` and `BACKEND_URL`
   to the Render URL. Deploy. Copy the Vercel URL.
7. **Render:** set `PUBLIC_APP_URL` and `CORS_ORIGINS` to the Vercel URL. Save; it redeploys.
8. Locally:
   - `verify_production.py --backend <render> --frontend <vercel>`
   - `smoke_test_deployment.py ... --with-schedule`
9. Manual checklist: `PRODUCTION_DEPLOYMENT.md` §8 (sign up, run, webhook, form, schedule).
