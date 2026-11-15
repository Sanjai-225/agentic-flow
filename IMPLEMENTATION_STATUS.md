# Implementation Status

_Last updated: 2026-11-15 — Milestone 1 complete and validated. Milestones 2–4 are not authorized._

## Milestone 1 — Core executable workflow engine: COMPLETE

### What works (verified)
- **Baseline.** `backup-phase2-phase3` was fast-forwarded into `testing`, which brings the Gemma reviewer, the Gemini primary/fallback chain and the design registry.
- **Canonical schema v2** (`backend/app/schemas/workflow.py`):
  - Each node has `operation`, `inputs`, `retry`, `timeout_seconds`, `on_error` and `ui.position`; each edge has `source_port`/`target_port`.
  - `start_nodes`/`end_nodes` are derived from the graph when omitted.
  - v1 documents still validate. The v1→v2 upgrader is `services/workflow_upgrade.py`; nodes bound to an external tool become `unsupported:<type>`.
- **Registry**: 9 executable operations plus 24 design-only types.

  | Operation | Notes |
  |---|---|
  | `core.manual_trigger` | Run payload becomes the trigger output |
  | `core.webhook_trigger` | Secret hashed token; method check; 1 MB body limit; sensitive headers dropped |
  | `core.set` | Typed fields; dotted paths create nested objects; optional keep-input |
  | `core.json_parse` | |
  | `core.filter` | Per-item `{{item.x}}` rules |
  | `core.transform` | Declarative mapping |
  | `core.if` | `true`/`false` ports; passes data through |
  | `core.end` | Sets the workflow output |
  | `http.request` | See below |

  `http.request` supports methods, query, headers, json/form/raw bodies, bearer/basic/header credentials, timeouts, a 5 MB response cap, per-hop SSRF checks on redirects, and categorised errors (401/403 → AUTH_FAILURE, 429 → RATE_LIMIT, 5xx → retryable PROVIDER_ERROR).
- **Engine**:
  - The planner checks unsupported/design-only operations, config models (extra keys rejected), graph topology, a single trigger, port validity, cycles, reachability, static references (must point upstream) and credential ownership.
  - The runner executes sequentially in topological order. Only edges whose port matches the source's route are active, so only the selected branch runs. Multiple active parents are combined as `{node_id: output}`.
  - Retries are bounded, with exponential backoff and jitter. Side-effecting requests (non-GET/HEAD/OPTIONS HTTP) are never auto-retried.
  - Node timeouts, a maximum execution duration, cancellation at node level, and `on_error: continue`.
  - Every state transition is persisted, including resolved inputs (redacted), outputs, errors, route, attempts, durations and logs.
  - On startup, interrupted runs are marked failed with "interrupted by restart".
- **Expressions**: `{{nodes.<id>.output...}}`, `{{trigger...}}`, `{{input...}}`, `{{item...}}` (Filter only), `{{execution.id}}`, `{{workflow.*}}`, and `| default(<json>)`. A whole-string expression keeps the native type. Errors are explicit: INVALID_MAPPING, or MISSING_INPUT with field, expression and suggestion. No `eval`.
- **Persistence and auth**:
  - SQLite with SQLAlchemy 2 async, plus an Alembic migration (`0001`) that is auto-applied on startup.
  - Tables: users, workflows, workflow_versions (immutable per save), executions, node_executions, execution_logs, credentials (Fernet-encrypted).
  - Email/password authentication with Argon2 and JWT. Every resource is user-scoped; other users get 404.
- **API**:
  - `/api/auth/{register,login,me}`
  - `/api/workflows` CRUD, `/validate` (both unsaved and saved), `/{id}/run` (async, or `?wait=true`), `/{id}/executions`, `/{id}/webhook`
  - `/api/executions/{id}`, `/{id}/cancel`
  - `/api/webhooks/{id}/{token}`
  - `/api/credentials`
  - `/api/registry/*`, which now includes execution metadata, config JSON schema and UI field hints
  - `/api/workflows/generate`, which now requires login, runs off the event loop and returns v2 with `execution_readiness`
- **AI designer integration**:
  - The prompt contains the exact config example and output fields for each executable operation.
  - Config, port and mapping errors on executable nodes go back into the existing repair loop. Design-only nodes are allowed, and the generator falls back to the best structurally valid design.
- **Frontend** (Next.js, dark glass theme):
  - Login and register.
  - Workflow list with last-run status.
  - Editor: searchable node library, where design-only nodes are hidden by default and flagged.
  - Canvas: connect, delete and duplicate nodes; named If ports.
  - Config panel driven by the registry: expression inputs, conditions, set-fields, key/value, JSON, credential picker, webhook URL creation, retry/timeout/on-error settings, and a data picker built from real upstream outputs.
  - Save, Validate and Run (with a JSON payload dialog), and Cancel.
  - AI Designer drawer that loads into the same editor.
  - Credentials dialog.
  - Bottom panel: Execution (node list, plus input/output/error/log inspector with suggestion and correlation id), History, and Problems.
  - Node status comes only from polling the backend.
  - A generic same-origin proxy (`app/api/[...path]`) replaces the per-route proxies.

### Acceptance tests (all passing)
| # | Test | Evidence |
|---|---|---|
| 1 | Save and reload | `test_execution_api.py::test_manual_workflow_save_and_reload_with_versions` |
| 2–7, 10 | Real execution, data flow, Set, If branch, only branch runs, real HTTP | `test_demo_workflow_true_branch_runs_http_against_real_server`, `test_demo_workflow_false_branch_skips_http` (real local uvicorn server). Also checked live against `https://httpbin.org/post` |
| 8 | Invalid mappings | `test_missing_reference_fails_node_with_understandable_error`, `test_invalid_static_mapping_is_rejected_before_execution`, `test_engine_expressions.py` |
| 9 | Unsupported nodes rejected before run | `test_unsupported_nodes_are_rejected_before_execution`, `test_engine_planner.py` |
| 10 | History shows real I/O | `test_execution_history_lists_real_runs` |
| 11 | AI-designed workflow executes | `test_generated_workflow.py` (mock designer). **Live:** real Gemini produced a fully executable Manual → Set → If → HTTP → End design, which saved, validated and ran to completion (HTTP 200, false branch skipped) |

### Test results (exact, 2026-11-15)
**Backend**
- `python -m pytest -q`: **163 passed, 2 skipped**. The 2 skipped are `live` tests, which only run when selected with `-m live`.
- `ruff check app tests alembic/env.py`: all checks passed.

**Frontend**
- `npm test` (vitest): **25 passed**.
- `npm run typecheck`: OK.
- `npm run lint`: OK, with 1 pre-existing warning: the Google Fonts `<link>` in `layout.tsx`.
- `npm run build`: OK. A build run while `next dev` is running fails on a stale `.next` folder; delete `.next` first.

**Live runs against a real backend** (scratchpad scripts, not committed)
- The demo workflow ran against httpbin.org; both branches were verified.
- Gemini → save → run, as described under acceptance test 11.

**Not verified**
- Clicking through the UI in a real browser. The Chrome automation extension kept dropping its tab group. The UI is covered by component tests and a clean production build.

### Environment variables
- **Existing:** `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_REVIEWER_MODEL`, `MAX_GENERATION_RETRIES`, `MAX_REVIEW_CORRECTION_ATTEMPTS`, `ENABLE_WORKFLOW_REVIEW`, `MOCK_DEV_MODE`, `CORS_ORIGINS`.
- **New:**

  | Variable | Default / behaviour |
  |---|---|
  | `APP_ENV` | `development`. In production, `JWT_SECRET` and `CREDENTIALS_ENCRYPTION_KEY` are required |
  | `DATABASE_URL` | `sqlite+aiosqlite:///backend/agentic_flow.db` |
  | `DB_AUTO_MIGRATE` | `true` |
  | `JWT_SECRET` | Dev fallback with a warning in docs |
  | `JWT_EXPIRES_MINUTES` | `720` |
  | `CREDENTIALS_ENCRYPTION_KEY` | Fernet key. In dev it is derived from the JWT secret |
  | `HTTP_ALLOW_PRIVATE_NETWORKS` | `false` |
  | `HTTP_MAX_RESPONSE_BYTES` | |
  | `PUBLIC_BASE_URL` | Used to build webhook URLs |
  | `EXECUTION_MAX_DURATION_SECONDS` | `900` |
  | `WEBHOOK_MAX_BODY_BYTES` | |

- **Frontend:** `NEXT_PUBLIC_API_URL` makes the browser call the backend directly (needs CORS). When it is empty, `BACKEND_URL` is used by the server-side proxy.

### Known limitations / remaining issues
- **In-process runner.** A restart mid-run marks that run failed; resuming is Milestone 4. Vercel/serverless deployment cannot run background executions or keep SQLite.
- **Single process only.** Cancel signals reach only executions running in the same process.
- **Not implemented yet** (registered as design-only so the UI and planner flag them): Schedule trigger, app event triggers, merge/switch/loop/wait/parallel/join, and error routes.
- **SSRF.** Checks run at resolution time; DNS rebinding is not fully mitigated.
- **Auth.** JWTs live in `localStorage`. There is no refresh token and no login rate limiting.
- **Live designer behaviour.** Gemini latency with review enabled was 78–90 s per generation. The live designer can still pick wrong output paths that only fail at runtime (shown clearly as MISSING_INPUT).
- **ChatPanel.** Generating replaces the canvas contents; there is no merge.

### Next step
Milestone 2 (AI/Agent node), **once it is authorized**. Before coding it, verify current LangChain/LangGraph APIs and the provider model IDs.

## Key file map
| Concern | Location |
|---|---|
| Schema / upgrade | `backend/app/schemas/workflow.py`, `backend/app/services/workflow_upgrade.py` |
| Registry | `backend/app/registry/{node_registry,executable_nodes,configs,examples}.py` |
| Engine | `backend/app/engine/{contracts,expressions,conditions,planner,runner,worker,redaction}.py` |
| Executors | `backend/app/executors/{core,http}.py` |
| Persistence | `backend/app/db/`, `backend/alembic/`, `backend/app/services/{workflow_store,execution_store,credentials}.py` |
| API | `backend/app/api/` |
| Frontend editor | `frontend/components/editor/`, `frontend/store/editorStore.ts`, `frontend/lib/` |
| Tests | `backend/tests/`, `frontend/tests/` |
