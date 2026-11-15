# Implementation Status

_Last updated: 2026-11-15 — Milestone 1 complete. **Milestone 2 implemented, validated and committed on `testing`**. One item is still open: live OpenAI and Anthropic *inference*, blocked because both provider accounts have no credit (not a code issue). Milestones 3–4 not authorized._

## Production deployment package (Vercel + Render + Supabase): PREPARED, NOT DEPLOYED (uncommitted on `testing`)

- **Free-tier revision.** Render `plan: free`, auto-migrate at startup, Docker removed. Free-tier limits: see `docs/PRODUCTION_DEPLOYMENT.md`.

- **Prepared:**
  - `render.yaml` (validated against the official schema) and `frontend/vercel.json`.
  - PostgreSQL/Supabase support: asyncpg + psycopg, session pooler, TLS, pooling.
  - RLS migration `0003`.
  - Production config gate, `/health/ready`, configurable CORS (removed the always-on `*.vercel.app` credentialed regex).
  - Deployment scripts in `backend/scripts/`.
  - Optional Dockerfile.
- **Guide:** `docs/PRODUCTION_DEPLOYMENT.md`. **Report:** `docs/DEPLOYMENT_READINESS_REPORT.md`.
- **Validated locally:** backend 414 passed / 13 skipped; frontend 62 passed, build OK; production-like stack verify 17/19 (2 expected http-only failures) and smoke test 12/12.
- **Open:** a real PostgreSQL run of the suite and migrations (blocked in this session), `docker build`, and the platform deployment itself.

## Milestone 2 — AI Agent, providers, AI Generate, triggers, flow nodes: VALIDATED (one external item open)

All phases (0–7) are implemented, every workflow A–I passes end to end on a real running stack, and cross-provider fallback is verified **live**.

**Open item:** OpenAI and Anthropic inference. With the configured keys:
- **Accepted:** live connection tests list all catalogue models (`gpt-6-astra`, `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-luna`; `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`).
- **Blocked:** every generation request is refused for billing. OpenAI returns 429 "You have no credits remaining", and Anthropic returns 400 "Your credit balance is too low". The raw provider SDKs fail the same way.

**To close it:** add credit to both accounts, then run `python scripts/compare_ai_models.py --providers openai anthropic` and `python -m pytest -m live tests/test_ai_live.py -s`.

### What was built (per phase)

| Phase | Result | Status |
|---|---|---|
| 0 Stabilization | Milestone 1 fix list (a)–(f): predictable ids with "did you mean" suggestions, output fields before the first run, no Set placeholders, readable conversion errors, classified Gemini errors, typed JSON editors | Implemented and tested |
| 1 Cleanup | 24 design-only types removed from the registry; legacy map (`registry/legacy.py`); legacy workflows preserved and never remapped; designer and reviewer prompts generated only from executable operations; reviewer gets deterministic planner facts and can never pass an invalid plan; mock designer emits only executable workflows; design-only toggle removed | Implemented and tested |
| 2 Providers | `app/ai/`: verified catalogue, LangChain adapters (ChatOpenAI on the Responses API, ChatAnthropic, ChatGoogleGenerativeAI), router with bounded retries and eligible-only fallback, error normalisation, usage records, provider credentials (encrypted, masked, editable, real connection test), platform keys opt-in in production | Implemented. Gemini live-tested; OpenAI and Anthropic **not live-tested** |
| 3 Agent | `ai.agent`: LangGraph `StateGraph` with a guarded tool loop; secure tool registry with 6 real tools; allowlist and policy enforcement; structured output with jsonschema validation and bounded repair; all limits; traces with no chain-of-thought | Implemented and tested; live on Gemini |
| 4 AI Generate | `ai.generate`: text or schema-validated typed JSON; no tools, no fallback | Implemented and tested; live on Gemini |
| 5 Triggers | Form Submission Trigger (public page, validation, honeypot, rate limit, size cap, rotation) and Schedule Trigger (DB-driven scheduler, DST-aware, misfire policy, unique-claim duplicate protection); workflow active flag | Implemented and tested; live in E2E |
| 6 Flow nodes | Switch (dynamic case ports), Merge (sequential synchronisation), Loop Over Items (real per-item body execution), Date & Time, Array | Implemented and tested; live in E2E |
| 7 | End-to-end verification, docs, `.env.example`, pinned requirements | Done (see the results below) |

- **Active library:** 9 → 18 executable operations; all 24 design-only types removed. Detail: `docs/NODE_CATALOGUE.md`.
- **New operation ids:** `ai.generate`, `ai.agent`, `core.form_trigger`, `core.schedule_trigger`, `core.switch`, `core.merge`, `core.loop`, `core.datetime`, `core.array`.
- **Migration:** `0002` adds `workflows.active`, `credentials.updated_at`, `ai_usage_records`, `workflow_forms`, `workflow_schedules` and `schedule_occurrences`. It is auto-applied on startup.
- **Docs:** `docs/NODE_CATALOGUE.md`, `docs/AI_PROVIDERS_AND_AGENT.md`, `docs/TRIGGERS.md`, and an updated `docs/MASTER_IMPLEMENTATION_PLAN.md`.

### Verified provider models (2026-11-15)

| Provider | Models | Evidence |
|---|---|---|
| Gemini | `gemini-3.5-flash` (default), `gemini-3.5-flash-lite`, `gemini-3.8-flash` | Live `models.list` plus real calls. Tool calling succeeded on 3.5-flash and 3.5-flash-lite. 3.8-flash succeeded for structured generation but returned 504/503 "high demand" on tool calls during verification. |
| OpenAI | `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6.1-terra`, `gpt-6-luna` | Official model docs only; **not live-tested** |
| Anthropic | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` | Anthropic models reference only; **not live-tested** |

`gemini-2.5-pro` and `gemini-2.5-flash` were removed: `models.list` still lists them, but generation returns 404 "no longer available to new users".

### Final verification results (2026-11-15)

**Backend**
- `python -m pytest -q`: **387 passed, 11 skipped**. The 11 skips are `live`-marked tests, not selected by default. Inference in the default suite is mocked (`tests/fake_llm.py`).
- `python -m pytest -m live tests/test_ai_live.py tests/test_generated_workflow.py tests/test_http_node.py`: **5 passed, 6 skipped**.
  - Passed live: Gemini AI Generate (structured), Gemini Agent with real `data_aggregate` + `calculator` calls, Gemini connection test, Gemini AI designer, HTTP node against httpbin.org.
  - Skipped: the OpenAI ×3 and Anthropic ×3 live tests (no keys).
- `python -m ruff check app tests alembic/env.py`: clean.
- `ruff format --check`: 79 files would be reformatted. No formatter is configured or enforced in this repo, so nothing was reformatted.

**Frontend**
- `npm test`: **59 passed** (6 files).
- `npm run typecheck`: OK.
- `npm run lint`: OK, with the 1 pre-existing font warning only.
- `npm run build`: OK, including the new `/forms/[formId]` route.

**Migrations**
- Fresh DB: upgrade → downgrade to 0001 → upgrade OK.
- A **copy** of the real dev DB upgraded 0001 → 0002. Its 2 workflows, 8 versions and 4 executions are preserved and all workflows are active.
- On that copy, the old AI-designer workflow keeps its legacy operations (`llm_agent`, `database_query`, …) and each is reported as a removed type. The Milestone 1 workflow is still valid.

**End-to-end**
- **Setup:** real uvicorn backend (dev-DB copy, SSRF protection on, scheduler on) plus a production Next.js server. Real httpbin.org, live Gemini, and the real public form URL through the frontend proxy. Scripts are kept outside the repo.

| Workflow | Result |
|---|---|
| A deterministic regression | PASS: both branches, real HTTP, typed output |
| B AI Generate | PASS: LIVE Gemini, typed JSON, usage recorded, history |
| C Agent task 1 | PASS: LIVE structured classification |
| D Agent task 2 | PASS: LIVE `data_aggregate` executed, validated args, structured result. The re-run also exercised a LIVE fallback (primary 429 quota → fallback) |
| E Agent, multiple tools | PASS: LIVE `data_aggregate` → `calculator` → `datetime`, 4 iterations, bounded |
| F Form | PASS: public page served, invalid → 422 and no run, valid → run on the correct branch (high/low) |
| G Schedule | PASS: the real scheduler fired at the configured minute, LIVE AI Generate, state persisted, next run advanced, one execution per occurrence; the schedule survived a backend restart |
| H Switch + Merge | PASS on the re-run, after fixing a defect found by the first run (below) |
| I Loop | PASS: the body ran once per item, results collected |
| Security | PASS: workflow, execution, form and credential isolation; SSRF blocked on the live server; API key masked, never in execution records or server logs; another user cannot use the credential |

**Defects found by live verification and fixed (with regression tests)**
1. **Switch:** all cases were resolved before evaluation, so a later case's missing field failed the node even after an earlier case matched. Cases are now resolved lazily per case.
2. **Provider error classification:** a connection reset surfaced as aiohttp `TransferEncodingError(code=400)` and was treated as a non-retryable HTTP 400. Transport errors are now classified first, as retryable and fallback-eligible.
3. **`data_aggregate`:** Gemini sent records as JSON strings because list items were untyped. Items are now explicitly typed, and JSON-encoded records are decoded strictly.
4. **Model catalogue:** removed `gemini-2.5-*` (404) and made `gemini-3.5-flash` the default.
5. **Frontend schedule preview:** it crashed while an invalid time zone was being typed. Formatting is now safe.

The second full E2E run hit the Gemini **free-tier daily quota** (429 `RESOURCE_EXHAUSTED`) on `gemini-3.5-flash`. The router classified it correctly, retried within bounds and reported it. The affected checks were re-run with `gemini-3.5-flash-lite` and passed 6/6.

### Final validation with configured provider keys (2026-11-15)
- **Backend:** `python -m pytest -q` gives **391 passed, 13 skipped** (the opt-in live tests). Ruff is clean.
- **Frontend:** 59 tests passed, typecheck OK, lint shows only the pre-existing font warning, production build OK.
- **Live:** `python -m pytest -m live tests/test_ai_live.py tests/test_generated_workflow.py tests/test_http_node.py` gives **9 passed, 4 failed**.

  | Live check | Result |
  |---|---|
  | Gemini (`gemini-3.5-flash-lite`) AI Generate | PASS (structured) |
  | Gemini Agent with real `data_aggregate` + `calculator` calls | PASS |
  | Connection tests: OpenAI, Anthropic, Gemini | PASS (all keys accepted; models listed) |
  | Cross-provider fallback OpenAI → Gemini | PASS (OpenAI billing failure; reason recorded) |
  | Cross-provider fallback Anthropic → Gemini | PASS (Anthropic billing failure; reason recorded) |
  | AI designer | PASS |
  | HTTP node against httpbin.org | PASS |
  | AI Generate + Agent on OpenAI `gpt-6.1-sol` | FAIL: billing only ("no remaining credit or quota") |
  | AI Generate + Agent on Anthropic `claude-sonnet-5-5` | FAIL: billing only ("no remaining credit or quota") |

- **End to end:** the A–I suite on a fresh migrated copy of the dev database gives **29/29 PASS**. Workflow C ran with an OpenAI primary and a Gemini fallback, and switched live with the reason recorded.
- **Model comparison:** `scripts/compare_ai_models.py` found `gemini-3.5-flash-lite` passing all checks. `gemini-3.5-flash` hit the free-tier daily quota. `gemini-3.8-flash` returned 503 "high demand" for structured output, and its tool calls took about 104 s. OpenAI and Anthropic could not be compared because of billing.
- **Fixed during this validation:** billing errors (OpenAI 429 "no credits", Anthropic 400 "credit balance too low", Gemini quota) were reported as "bad request" or retried pointlessly. They now get a clear message, are not retried, and are fallback-eligible. Covered by regression tests.
- **`.env` placeholders:** values such as `your_openai_api_key_here` are treated as "no key" everywhere.

### Known limitations / not done
- **OpenAI and Anthropic:** not live-tested, so cross-provider live fallback is unverified. Needs `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`.
- **`gemini-3.8-flash`:** intermittently 503/504 under provider load. Configure a fallback model.
- **Single process:** rate limiting and cancellation work per process (in-memory). Schedule duplicate protection is database-enforced and safe across workers.
- **DNS rebinding:** SSRF checks run at resolution time, so rebinding between the check and the connection is not fully mitigated (unchanged from Milestone 1).
- **Branches are sequential:** Merge is sequential synchronisation, not parallel execution.
- **Loops:** nested loops are not supported. Body node history keeps the last iteration plus the first 100 iteration summaries.
- **No cost figures:** pricing data is unverified, so no cost estimates are produced; token usage is provider-reported only.
- **Agent checkpointing:** none on disk. The state is serialisable, but durable pause/resume, human approval, wait and restart recovery remain Milestone 4.
- **Composio** and application integrations are Milestone 3.
- **UI not clicked through in a browser:** components are covered by vitest and a production build. Public form pages were served and submitted against the running servers.

### Manual configuration still needed
1. Replace the placeholders `OPENAI_API_KEY=your_openai_api_key_here` and `ANTHROPIC_API_KEY=your_anthropic_api_key_here` in `backend/.env` (placeholders are treated as no key). Then run `python scripts/compare_ai_models.py --providers openai anthropic` to pick a primary and fallback model per provider, and `python -m pytest -m live tests/test_ai_live.py -s`.
2. Production: set `APP_ENV=production`, `JWT_SECRET`, `CREDENTIALS_ENCRYPTION_KEY` and `PUBLIC_APP_URL`/`PUBLIC_BASE_URL`. Set `AI_ALLOW_PLATFORM_KEYS=true` only if platform keys should be shared.
3. Run `pip install -r backend/requirements.txt` for the new pinned LangChain, LangGraph, croniter and tzdata packages.

### Phase 0 details

### Phase 0 baseline (before any change, 2026-11-15)
- **Git:** branch `testing`, HEAD `ae9d0fc`, working tree clean.
- **Backend:** `python -m pytest -q` gave **163 passed, 2 skipped** (`live`). `ruff check` was clean.
- **Frontend:** `npm test` gave **26 passed** (the Milestone 1 notes said 25; the actual count was 26). `typecheck` OK. `lint` OK, with 1 pre-existing warning (Google Fonts `<link>` in `layout.tsx`).
- **Registry:** **33 types: 9 executable, 24 design-only, 0 partial.** The exact list is in `docs/NODE_CATALOGUE.md`.

### Phase 0 stabilization: Milestone 1 fix list (all six were still present; all now fixed)

| # | Item | Fix | Status |
|---|------|-----|--------|
| a | Predictable node ids and suggestions for invalid ids | Each registry definition has an `id_prefix`. The editor's `uniqueNodeId` returns the smallest free `<prefix>_<n>` (`set_1`, `http_1`). Previously it started at `nodes+1`, giving ids like `set_4`. The designer prompt uses the same convention. The planner and the runtime resolver add "Did you mean 'set_1'?" using `difflib`, or list the upstream nodes. | Implemented and tested |
| b | Data fields before the first run | New `infer_output` hook on `NodeDefinition` (`registry/output_hooks.py`), aggregated by `engine/output_fields.py`. Fields come from config for Set, Transform, Manual Trigger and End, from the schema for HTTP, Webhook and Filter, and are inherited for If and an End without output. Exposed as `POST /api/workflows/output-fields`. The data picker shows them as "expected" until a real run exists. Cycles and unknown or legacy operations are handled safely. | Implemented and tested |
| c | Set placeholder field and empty values | `core.set` now defaults to `fields: []`. `SetField` rejects blank names, `a..b` names, and empty values unless `type: string`. Planner messages from our validators are kept verbatim and readable. | Implemented and tested |
| d | Number-conversion errors | `coerce` produces messages like "Field 'amount' expects a number such as 42 or 3.5 …, but the value is the text 'twelve'", with a suggestion and details. Raw Python text is gone. NaN and Infinity are rejected. | Implemented and tested |
| e | Friendly Gemini errors | New `services/llm_errors.py` classifies errors as missing or invalid key, permission, quota, timeout, network, model not found, bad request, unavailable, empty or unknown. The REST path keeps Google's error body; API keys are scrubbed from all messages. A bad key or a network failure stops trying further models, and the SDK is skipped when it cannot help. `/api/workflows/generate` returns `{category, message, suggestion}`, and the UI shows the message plus the suggestion. | Implemented and tested; also checked live against Gemini (invalid key → `invalid_api_key`, no key leaked; real key → success) |
| f | Typed JSON editors | Backend typing was already correct, and is now covered by a regression test. New widgets: `json_template` (End output, HTTP body) and `keyvalue_json` (Transform mappings). They accept JSON with unquoted `{{refs}}` and store whole-reference strings, so numbers, objects and arrays keep their type. Invalid objects are reported, never saved as strings. | Implemented and tested |

### Phase 0 files
- **Backend, new:**
  - `app/registry/output_hooks.py`
  - `app/engine/output_fields.py`
  - `app/services/llm_errors.py`
  - `tests/test_output_fields.py` (15 tests)
  - `tests/test_m1_stabilization.py` (50 tests)
- **Backend, modified:**
  - `app/schemas/registry.py`: widgets, `id_prefix`, `infer_output`
  - `app/registry/executable_nodes.py`: hooks, prefixes, Set default, widgets
  - `app/registry/configs.py`: SetField validation
  - `app/registry/node_registry.py`: id prefixes in the designer catalogue
  - `app/engine/planner.py`: readable validator messages and id suggestions
  - `app/engine/expressions.py`: id suggestions
  - `app/executors/core.py`: conversion errors
  - `app/services/llm_service.py`: error classification and early stop
  - `app/services/workflow_reviewer.py`
  - `app/api/workflow.py`: structured errors
  - `app/api/workflows.py`: output-fields endpoint
- **Frontend, new:** `tests/stabilization.test.tsx` (14 tests).
- **Frontend, modified:**
  - `components/editor/fields.tsx`: JSON template parsing, `JsonTemplateEditor`, JSON-mode `KeyValueEditor`
  - `components/editor/NodeConfigPanel.tsx`: new widgets, inferred fields in the data picker
  - `lib/workflowMapping.ts`
  - `lib/api.ts`
  - `types/workflow.ts`
- **Docs:** `docs/NODE_CATALOGUE.md` (new), this file, and `docs/IMPLEMENTATION_PROGRESS.md`.

### Phase 0 test results (after the changes)
- **Backend:** `python -m pytest -q` gave **228 passed, 2 skipped** (the 2 `live` tests were not selected). `ruff check app tests alembic/env.py` was clean.
- **Frontend:**
  - `npm test`: **40 passed** (5 files).
  - `npm run typecheck`: OK.
  - `npm run lint`: OK; same single pre-existing warning.
  - `npm run build`: OK.
- **Live:** one Gemini designer call with the configured key succeeded, and one with a deliberately invalid key returned the classified error.

### Behaviour changes to be aware of
- A saved workflow whose Set node has an empty value (with a type other than `string`) now fails validation with a clear message. Before, it ran and produced `""`, or `False` for booleans. New Set nodes start with no fields.
- Set `number` fields reject `NaN` and `Infinity`.
- `/api/workflows/generate` error `detail` is now an object `{category, message, suggestion, status_code, model}` instead of a plain string. The frontend already reads `detail.message`.

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
