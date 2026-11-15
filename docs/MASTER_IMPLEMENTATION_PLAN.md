# Agentic Flow — Master Implementation Plan

> **Execution authorization:** the plan is divided into exactly **4 sequential milestones**. Only **Milestone 1** is authorized. Milestones 2–4 stay documented, but nothing in them is implemented until explicitly authorized.
>
> **Order of work for this session:**
> 1. First project modification: copy this plan verbatim to `docs/MASTER_IMPLEMENTATION_PLAN.md`.
> 2. Create `docs/IMPLEMENTATION_PROGRESS.md`. It holds a milestone checklist (M1–M4: status, date, acceptance-test results) and starts with M1 = in progress and M2–M4 = not started / not authorized.
> 3. Implement Milestone 1 only (Parts 1A–1D below). Test it, fix failures, and demo it end to end.
> 4. Update `IMPLEMENTATION_STATUS.md` and `docs/IMPLEMENTATION_PROGRESS.md` with exact test results, missing configuration and remaining issues. **Stop.** M1 is not claimed complete if any acceptance test fails.
>
> Milestone 1 lays foundations for later milestones without implementing their features. These extension points are built now:
> - registry fields (`credentials`, `side_effects`, `requires_approval`, `idempotent`)
> - the `waiting`/`paused` status enums
> - the `credentials` table and service
> - executor registration
>
> These are **not** built in M1: the `ai.*` nodes, LangChain/LangGraph, Composio, approvals, pause/resume.

## Context

Agentic Flow is currently a **design-only** AI workflow generator: a prompt goes to Gemini, which returns JSON. That JSON passes Pydantic and graph validation and is drawn read-only in React Flow. The goal is to turn it into a **genuinely executable** n8n-style automation platform with these capabilities:
- manual and AI-generated editing
- a node registry
- a durable execution engine
- a universal LangChain/LangGraph Agent node
- Composio app integrations
- execution inspection and debugging

None of these exist today.

### Audit summary (verified in repo, branch `testing` @ a55435f)

| Area | State |
|---|---|
| Backend | FastAPI (`backend/app/main.py`), Python 3.13. `requirements.txt` is unpinned (fastapi, uvicorn, python-dotenv, pydantic, google-genai) |
| Routes | `GET /health`, `POST /api/workflows/generate` (`backend/app/api/workflow.py`) |
| AI pipeline | `services/llm_service.py`: REST-first then google-genai SDK, model chain `gemini-3-flash-preview` → … with a 12s timeout. `services/workflow_generator.py`: generate → `WorkflowSchema` → `GraphValidator` → repair loop. The reviewer uses the same Gemini chain; it does **not** use Gemma, and it returns `passed=True` when its output can't be parsed |
| Schema | `schemas/workflow.py`: free-form `node.type`, `tool{name,operation,status}`, `edges{source,target,label,condition}`, `start_nodes`, `end_nodes`. There is no version, operation id, port, input mapping or position |
| Graph validator | `validators/graph_validator.py`: reachability, self-loops; cycles only produce a warning. Works and will be reused |
| Mock mode | `services/mock_workflow_generator.py`: 4 keyword-selected designs. Used by the tests |
| Execution / DB / auth | **None** |
| LangChain / LangGraph / Composio / Anthropic / OpenAI | **None** |
| Tests | `backend/tests/test_workflow.py`: 12 pytest tests that depend on mock mode |
| Frontend | Next.js 14 App Router, @xyflow/react 12.12.1, Tailwind 3, light theme. One page: ChatPanel plus a read-only canvas. A single `custom` node type with unnamed handles. No `onConnect`, palette, config panel, save/load, execution, tests or eslint |
| Dead code (frontend) | `WorkflowToolbar.tsx` and `PromptInput.tsx` are unused. `services/workflowApi.ts` is unused and duplicated by an inline fetch in ChatPanel. The frontend sends `source_handle`/`target_handle`, which the backend doesn't have |
| Docs drift | The default model in README, `.env.example` and the code disagree. `.env` sets `GEMINI_FALLBACK_MODEL`, `GEMINI_REVIEWER_MODEL` and `MAX_REVIEW_CORRECTION_ATTEMPTS`, but the testing code ignores them |
| Local branch `backup-phase2-phase3` (74beac0) | Has the Gemma reviewer (`gemma-4-31b-it`), the chain `gemini-3.8-flash` → `gemini-3.5-flash-lite` → `gemini-3-flash-preview` (30s), a 26-type design registry (`registry/node_registry.py`, `schemas/registry.py`, `api/registry.py`), `schemas/review.py` and registry-aware prompts |
| Repo rules (`agent.md`) | Work on `testing`. Never push without confirmation. Never commit `.env`. Don't modify `agent.md` |

### Decisions you confirmed
1. **Baseline:** restore `backup-phase2-phase3` into `testing` first.
2. **Database:** SQLite plus SQLAlchemy 2.x, with Alembic migrations, kept Postgres-portable.
3. **Auth:** minimal built-in email/password (hashed passwords) with JWT. Every row is scoped by `user_id`.
4. **Runner:** an in-process asyncio worker. State is persisted after every node transition. Startup reconciles runs that were interrupted.

---

## MILESTONE 1 — Core executable workflow engine (AUTHORIZED)

Milestone 1 has four parts, done in order:
- **1A:** baseline and docs
- **1B:** schema, registry and engine
- **1C:** persistence, auth and API
- **1D:** frontend

Its acceptance tests are listed at the end of 1D.

### 1A — Baseline, audit docs, hygiene

1. Merge `backup-phase2-phase3` into `testing`, resolve conflicts, keep the Windows REST-first workaround, and get its tests green. Delete stale `__pycache__`.
2. Pin `requirements.txt` to the versions that are installed and working. Add `requirements-dev.txt` (pytest, pytest-asyncio, respx, ruff, mypy).
3. Add `backend/tests/conftest.py` to force `MOCK_DEV_MODE` and an empty API key, so automated tests never call live providers. Add a `live` pytest marker for real-provider tests, opt-in via `-m live`.
4. Frontend tooling: eslint (`eslint-config-next`), a `typecheck` script (`tsc --noEmit`), and vitest plus React Testing Library. Remove the dead components or wire them in.
5. Write the docs:
   - `docs/ARCHITECTURE_AUDIT.md` (the table above, expanded)
   - `docs/IMPLEMENTATION_PLAN.md` (milestone breakdown)
   - `IMPLEMENTATION_STATUS.md` (running record)
   - root `CLAUDE.md` (boundaries, commands, test rules, security rules, conventions, and the `agent.md` git rules)
   - `docs/MASTER_IMPLEMENTATION_PLAN.md` (this plan, written first)
   - `docs/IMPLEMENTATION_PROGRESS.md` (milestone tracker)
   - Fix the README and `.env.example` model drift.

### 1B — Schema, registry, engine

#### Target architecture (backend layout under `backend/app/`; entries marked M2/M3/M4 are created only in those milestones)

```
api/          workflow.py (generate, kept)  workflows.py (CRUD/validate/run)  executions.py
              webhooks.py  auth.py  registry.py  integrations.py(M3)  approvals.py(M4)
core/         config.py  security.py (JWT, hashing)  errors.py (error taxonomy)
db/           base.py  session.py  models.py  (Alembic in backend/alembic/)
schemas/      workflow.py (canonical v2 + v1 upgrader)  registry.py  review.py  execution.py  auth.py
registry/     node_registry.py (design + executable definitions)  definitions/*.py
engine/       contracts.py (ExecutionContext, NodeExecutionResult, NodeExecutor protocol)
              expressions.py (reference resolver)  conditions.py (safe condition DSL)
              planner.py (pre-run validation)  runner.py (scheduler/state machine)  worker.py (asyncio task mgmt)
executors/    triggers.py  data.py  control.py  http.py  ai.py(M2)  agent.py(M2)  integration.py(M3)
ai/           providers.py (model catalog + LangChain factory)  agent_graph.py  tools.py   (M2)
integrations/ base.py (IntegrationProvider protocol)  composio_provider.py  catalog.py   (M3)
services/     existing generator/reviewer/llm_service (preserved)  workflow_store.py  credentials.py
validators/   graph_validator.py (extended)
```

Each system has a fixed boundary:
- The designer and reviewer only emit and inspect canonical JSON.
- The registry is the single source of truth for which operations exist and which can run.
- The engine never imports React Flow concepts.
- Executors receive secrets only through `context.credentials` (a backend service). Secrets never appear in config or state.

#### Canonical workflow schema v2 (evolve `schemas/workflow.py`, no second schema)

- **Workflow fields:**
  - `schema_version: 2`, `workflow_id`, `version` (int, incremented on save), `name`, `description`
  - `trigger` (derived from the start node), `nodes`, `edges`
  - `start_nodes` and `end_nodes`, kept for compatibility
  - `settings` (default timeout, error policy)
  - `ui` (viewport)
- **Node fields:**
  - `id` (stable), `operation` (registry id such as `core.manual_trigger`, `core.set`, `core.if`, `http.request`), `type_version`
  - `label`, `description`, `config` (validated against the registry config model)
  - `inputs` (mapping name → expression/literal), `retry` and `timeout` overrides, `on_error: fail|continue|route`
  - `ui: {position:{x,y}, color?}`: presentation only, ignored by the engine
  - `tool` kept as optional legacy design metadata
- **Edge fields:** `id`, `source`, `target`, `source_port` (default `main`; If uses `true`/`false`; `error` comes later), `target_port`, `label`.
- **Upgrader:** a `v1 → v2` upgrader maps the legacy free-form `type` to an `operation` through an alias table in the registry (`trigger`/`manual_trigger` → `core.manual_trigger`, `condition` → `core.if`, `api_call` → `http.request`, and so on).
  - Anything that doesn't map becomes `operation: "unsupported:<type>"`. Such nodes still render and save, but the planner **rejects** them before execution with an `UNSUPPORTED_CAPABILITY` error.
  - `edge.condition` strings like "true"/"yes" map to `source_port`.
- **Generation prompts:**
  - Update the architect prompt (built from the registry, as on the backup branch) to emit v2 operations and config.
  - The reviewer additionally reports nodes that can't execute.
  - The frontend's stray `source_handle` field becomes `source_port`.

#### Node registry

Extend the backup branch's `NodeDefinition` with these fields:
- `operation_id`, `version`, `category`, `executable: bool`, `status: ready|design_only|needs_config`
- `config_model` (a Pydantic class, exported as JSON Schema for the UI), `input_schema`, `output_schema`
- `ports_in`, `ports_out` (static or dynamic)
- `credentials: [credential_type]`, `side_effects: bool`, `idempotent: bool`, `requires_approval: bool`
- `default_retry` / `timeout`, `ui` (icon, color, field widgets)

Executors register separately in `executors/__init__.py` (`register(operation_id, ExecutorClass)`). A node counts as executable only if an executor is registered for it and the registry marks it executable. A test enforces this invariant both ways.

The 26 design types stay in the registry as `design_only` (the AI can still sketch with them), but the UI and planner clearly flag them as non-executable.

`GET /api/registry/nodes` returns the definitions, config JSON schemas and executable status.

#### Execution engine

### Contracts (`engine/contracts.py`)
- **Executor:** `async execute(config: BaseModel, inputs: dict, ctx: ExecutionContext) -> NodeExecutionResult`
- **`ExecutionContext`:** workflow_id and version, execution_id, node_id, user_id, a read-only `state` view (only visible upstream outputs), `credentials` service, logger (writes `execution_logs`), a `cancel_event`, timeout, attempt number, correlation_id.
- **`NodeExecutionResult`:** `status` (success|failed|skipped|waiting), `output` (JSON-serialisable), `error: NodeError?`, `route: list[str]?` (the ports to follow), `metadata` (duration_ms, attempts, http status, usage).
- **`NodeError`:**
  - `category`: one of SCHEMA_VALIDATION, GRAPH_VALIDATION, UNSUPPORTED_CAPABILITY, MISSING_INPUT, INVALID_MAPPING, MISSING_CREDENTIALS, AUTH_FAILURE, PERMISSION_DENIED, PROVIDER_ERROR, MODEL_ERROR, TIMEOUT, RATE_LIMIT, NODE_EXECUTION, ENGINE_ERROR
  - also `message`, `technical_detail` (redacted), `retryable`, `field` (offending config/input path), `suggestion`

### Planner (pre-run, also backs `POST /workflows/{id}/validate`)
The planner checks, in order:
1. Schema v2
2. Every operation is registered and executable
3. Config validates against the node's config model
4. Graph validation: the existing GraphValidator, plus port validity (If must use `true`/`false`), exactly one trigger as the start node, and **cycles are an error** for v1 (loops come later)
5. Static expression references point at upstream ancestors
6. Required credentials are present

It returns a structured list of issues, each with node_id, field, category and suggestion.

### Runner (`engine/runner.py`): sequential, deterministic
- **Ordering:** topological order using the canonical edge order as a stable tie-break.
- **Activation:** a node runs when all of its incoming edges are resolved and at least one of them is *active*.
  - An edge is active when its source succeeded and its `source_port` is in the source's `route` (no route means `main`).
  - When none of a node's incoming edges is active, the node is marked `skipped`, and the skip propagates through its edges as inactive.
  - This gives "only the selected branch executes" and makes join semantics explicit.
- **Per node:**
  1. Resolve inputs (expressions).
  2. Validate the inputs.
  3. Persist `running`.
  4. Execute with `asyncio.wait_for(timeout)`.
  5. Apply retry: exponential backoff with jitter, bounded by `max_attempts`. Retries happen **only if** the error is retryable **and** (`not side_effects` or `idempotent` or an idempotency key is supported).
  6. Persist output, status and error.
  7. Select the outgoing edges.
- **Failure:** with `on_error: fail` (the default), the workflow fails and the remaining nodes become `skipped`. With `continue`, the error object becomes the output and execution follows `main`.
- **Statuses:**
  - Workflow: pending, running, completed, failed, paused, cancelled.
  - Node: pending, running, success, failed, skipped, waiting.
- **Cancellation:** a per-execution `asyncio.Event`, checked between nodes and passed to executors (httpx requests are cancelled).

### Expressions (`engine/expressions.py`)
- **Syntax:** `{{nodes.<id>.output.<path>}}`, `{{trigger.<path>}}` (alias), `{{execution.id}}`, `{{workflow.id}}`.
- **Resolution:**
  - A whole-string expression keeps the native type; an expression embedded in a string interpolates as text.
  - Paths support dot and `[index]` notation.
- **Errors:**
  - A reference to a node that isn't an upstream ancestor, or that was skipped, is an `INVALID_MAPPING` error.
  - A missing path is a `MISSING_INPUT` error, unless a `| default(...)` filter is configured.
  - A null value at the end of a path is allowed; null in the middle of a path is an error.
- **No eval:** a hand-written tokenizer is used, and only the run's own state is visible. That state is loaded per `execution_id` and `user_id`.

### Safe conditions (`engine/conditions.py`)
If and Filter use structured rules: `{left, operator, right}` with operators eq, neq, gt, gte, lt, lte, contains, not_contains, starts_with, ends_with, is_empty, not_empty, is_true, is_false, regex (bounded), combined with `all` or `any`. Arbitrary code is never executed.

### Milestone 1 executors

| Operation | Behavior |
|---|---|
| `core.manual_trigger` | Output is the run payload (JSON body of `/run`) |
| `core.webhook_trigger` | Has a per-workflow secret token. `POST /api/webhooks/{workflow_id}/{token}` starts a run with `{body, headers(filtered), query, method}`. Responds 202 with the execution id |
| `core.set` | Sets fields: list of `{name, value(expression), type}` plus `keep_input: bool` |
| `core.json_parse` | Parses `source` (expression) and fails with a clear error |
| `core.filter` | Takes an input array plus conditions; outputs `{items, kept, dropped}` |
| `core.if` | Evaluates conditions and returns `route=["true"]` or `["false"]` |
| `core.transform` | Maps fields: `{target_path: expression}`. Declarative, no code |
| `http.request` | Uses httpx. Supports method, url, query, headers and a JSON/form/raw body. Auth: none, bearer, basic, or header, taken from a stored credential reference. Timeout of at most 120s; response handling json/text, size cap of 5MB. Non-2xx becomes an error unless `ignore_http_errors`. SSRF guard: private, loopback and link-local addresses are blocked unless `HTTP_ALLOW_PRIVATE_NETWORKS=true` (enabled in tests and dev). Treated as a side effect for anything other than GET, HEAD and OPTIONS |
| `core.end` | Sets the workflow's final output from mapped inputs |

`core.merge`, switch, loop, wait, parallel and join are registered as `design_only` until the engine supports them.

### 1C — Persistence, auth, API

#### Persistence (SQLAlchemy 2.x async + aiosqlite, Alembic)

| Table | Columns |
|---|---|
| `users` | id, email, password_hash, created_at |
| `workflows` | id, user_id, name, current_version, webhook_token_hash, timestamps |
| `workflow_versions` | workflow_id, version, definition JSON (immutable), created_at |
| `executions` | id, workflow_id, workflow_version, user_id, status, trigger_type, input JSON, output JSON, error JSON, started/finished_at, correlation_id |
| `node_executions` | execution_id, node_id, operation, status, attempt, inputs JSON (redacted), output JSON, error JSON, route, started/finished_at, duration_ms |
| `execution_logs` | execution_id, node_id?, level, message, data, ts |
| `credentials` | user_id, type, name, encrypted_data (Fernet, key from `CREDENTIALS_ENCRYPTION_KEY`). Used by HTTP auth and provider keys |
| *Added in Milestone 3* | `integration_connections` |
| *Added in Milestone 4* | `approvals`, `checkpoints` |

Every query is filtered by `user_id`. A repository layer enforces this, and tests check cross-user denial for every resource.

On startup, executions still marked `running` from a previous process are set to `failed` with an `ENGINE_ERROR`: "interrupted by restart". Milestone 4 upgrades this to resume from a checkpoint where it is safe.

#### Auth
- **Endpoints:** `POST /api/auth/register|login`, `GET /api/auth/me`.
- **Passwords:** hashed with `pwdlib[argon2]` (or bcrypt).
- **Tokens:** PyJWT HS256, with `JWT_SECRET` from env; the app refuses to start in non-dev mode without it. A `get_current_user` dependency protects all routes except health, webhooks (token-auth) and OAuth callbacks (state-auth).
- **Generate endpoint:** remains usable while logged in.

#### API
- `GET/POST /api/workflows`
- `GET/PUT/DELETE /api/workflows/{id}` (PUT creates a new version)
- `POST /api/workflows/{id}/validate`
- `POST /api/workflows/{id}/run` returns `{execution_id}` with status 202
- `GET /api/workflows/{id}/executions`
- `GET /api/executions/{id}` (execution, node_executions, logs)
- `POST /api/executions/{id}/cancel`
- `POST /api/webhooks/{workflow_id}/{token}`
- `POST /api/workflows/generate` (kept; the response is upgraded to v2)

### 1D — Frontend (built on the existing Next.js app)
- **State:** add `zustand`, a small library that replaces the useState prop plumbing. Store slices: workflow, selection, execution.
- **Routes:** `/login`, `/workflows` (list), `/workflows/[id]` (editor), plus `/workflows/new`.
- **Editor layout:**
  - left: searchable **NodeLibrary** from `/api/registry/nodes`, with design-only nodes greyed out
  - center: **canvas**
  - right: **NodeConfigPanel**, rendered from the config JSON schema plus UI hints, with an expression input and an upstream-output picker
  - top: toolbar with Save, Validate, Run, and the AI Generate drawer (the existing ChatPanel)
- **Canvas:**
  - Enable `onConnect`, delete, duplicate and drag-to-add.
  - Named handles per registry port (If has true/false).
  - Positions are saved into `node.ui.position`.
  - Converters `canonicalToFlow()` and `flowToCanonical()` live in `lib/workflowMapping.ts` and are unit-tested for round-trips.
  - AI-generated workflows load into the same editor and are saved through the same API.
- **Execution:**
  - Run calls the backend, then the editor polls `GET /api/executions/{id}` every 750 ms until the run reaches a terminal state.
  - Node borders and badges reflect **backend** statuses only.
  - A bottom **ExecutionPanel** shows the run list, per-node inputs, output, error with suggestion, duration and logs.
  - An execution history tab lists past runs.
- **Validation:** planner issues are shown on the offending nodes and fields.
- **Visual design:** dark-first glass theme tokens in `globals.css` (`.dark` variables; translucent panels `bg-white/5 backdrop-blur-md`, restrained indigo accent, high-contrast text). Status colors: pending grey, running blue pulse, success green, failed red, waiting amber, skipped dimmed. Full refinement happens in Milestone 4.
- **API client:** consolidate on `services/workflowApi.ts` (typed, with auth header) and remove the inline fetch.

#### Milestone 1 acceptance tests (all automated unless noted)

| # | Test | Location |
|---|---|---|
| 1 | Save and reload round-trips | API test |
| 2–6 | Demo workflow **Manual → Set → If → HTTP (true branch) / End** runs. Asserts data flow, Set output, the chosen branch, and the false branch skipped | `tests/engine/test_demo_workflow.py` |
| 7 | HTTP node against a **real local endpoint**: a uvicorn test app started in a pytest fixture, plus an optional live `-m live` test against httpbin | |
| 8 | Bad mapping returns INVALID_MAPPING with node/field | |
| 9 | `unsupported:*` or design-only operation is rejected by the planner with 422 | |
| 10 | Execution detail API returns the real per-node inputs and outputs | |
| 11 | Mock-mode generation, then upgrade to v2, then plan and run for a generator template using only executable ops. Live generation is covered by a `-m live` test | |
| — | Unit tests: expressions, conditions, retry policy, registry↔executor invariant, user isolation, webhook token | |
| — | Frontend tests: mapping round-trip, config form rendering, status rendering from a mocked API | vitest |

**Milestone 1 completion gate:** every acceptance test above passes. Backend pytest, ruff, frontend lint, typecheck, vitest and build are all green. The demo workflow runs end to end through the real backend and UI. `IMPLEMENTATION_STATUS.md` and `docs/IMPLEMENTATION_PROGRESS.md` are updated. **Then stop.**

---

## MILESTONE 2 — Models, LLM node, universal Agent node (AUTHORIZED 2026-11-15)

> **As implemented:** the authorized Milestone 2 master prompt extended this section. It added node-library cleanup, the Form and Schedule triggers, Switch / Merge / Loop / Date & Time / Array, and Gemini and Gemma capability updates.
> - **Implementation records:** see `docs/NODE_CATALOGUE.md`, `docs/AI_PROVIDERS_AND_AGENT.md`, `docs/TRIGGERS.md` and `IMPLEMENTATION_STATUS.md`.
> - **Differences from the original sketch below:**
>   - `ai.llm_generate` and `ai.extract` became a single `ai.generate` node (text or schema-validated JSON).
>   - The agent has no on-disk checkpointer. Durable pause/resume is Milestone 4.
>   - Built-in tools are standalone read-only tools; they are not wrappers around workflow nodes.
>   - Platform keys are opt-in in production.

1. **Verify first:** check current package APIs against the official docs and pin versions: `langchain-core`, `langchain-anthropic`, `langchain-openai`, `langchain-google-genai`, `langgraph`, `langgraph-checkpoint-sqlite`. Python 3.13 compatibility must be confirmed. Model IDs must be verified against the provider docs before they are added. The brief's candidates (Claude Opus 5.5 / Sonnet 5.5, GPT-6.1 Sol / GPT-6 Astra, Gemini 3.8 Flash) are added only once confirmed.
2. **`ai/providers.py`:** a model catalog with these fields for each model:
   - provider, model_id, display_name, credential_env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) or a user credential reference
   - supports_tools, supports_structured_output, supported_params, context_limit, default_timeout, a lightweight flag
   - status computed at runtime (configured / missing_key)

   `get_chat_model(provider, model, params)` returns a ChatAnthropic, ChatOpenAI or ChatGoogleGenerativeAI instance. Unsupported parameters are rejected with a clear error. `GET /api/ai/models` exposes the catalog without any secrets.

   The existing Gemini workflow-designer pipeline stays on its current REST/SDK path, unchanged.
3. **`ai.llm_generate` executor:** takes provider, model, system prompt, prompt (expressions), temperature, max_tokens and timeout. Returns `{text, usage}`.
4. **`ai.extract` executor:** takes a user-defined JSON-schema output (converted to a Pydantic model dynamically) and uses `with_structured_output`. The result is validated, and a failed validation is a MODEL_ERROR.
5. **`ai.agent` (one universal node):**
   - **Config:** provider, model, instructions, task (expression), input mappings, `allowed_tools` (tool ids plus per-tool permissions), output_schema?, memory (none | per-workflow thread), max_iterations (default 8), timeout, token budget, temperature, `approval_required_for` (side-effect tools default to requiring approval), on_error.
   - **Runtime (`ai/agent_graph.py`):** a LangGraph `StateGraph` with a model node, a guarded tool node and a finalize node.
     - The guarded tool node does five checks: the tool is in the allowlist, the arguments pass the schema, the user is authorized, the approval policy is met, and the tool runs with a timeout. Invalid tool calls return a tool error message to the model and never execute.
     - Iteration, time and token limits apply; when a limit is hit, the run ends with a structured error.
     - The final output is validated against output_schema.
   - **Checkpointing:** a SQLite checkpointer keyed by `execution_id:node_id`, which prepares for approval interrupts in Milestone 4.
   - **Output:** `{final_output, structured?, status, tool_calls:[{tool, args(redacted), status, duration}], usage, duration_ms, iterations}`. Chain-of-thought is not exposed.
6. **Tool registry (`ai/tools.py`):** wraps selected executable nodes as LangChain tools: `http.request` and a safe `core.transform`/calculator. Milestone 3 adds Composio actions. Every tool has a JSON schema, a side-effect flag and an authorization hook.
7. **Frontend:** an AgentConfigPanel with model picker (showing configuration status), instructions, tool multi-select, limits and output-schema editor. A trace viewer appears in the ExecutionPanel.
8. **Tests:**
   - Mocked: a fake chat model built on LangChain's `GenericFakeChatModel` / a custom tool-calling fake covers tests 2–10 (tool call, no-tool completion, iteration cap, invalid tool rejection, structured validation, parent receives output).
   - Clear errors when credentials are missing (12) and when a provider fails (11), via mocked HTTP errors.
   - Live tests for each provider, under `-m live`. A provider is marked "supported" in the status doc only after its live test passes.

## MILESTONE 3 — Composio integrations (NOT AUTHORIZED YET)
1. **Verify first:** read the current Composio Python SDK docs (docs.composio.dev) for the package name, auth configs, `connected_accounts.initiate`, tool listing and schemas, and tool execution with `user_id`. Pin the SDK version.
2. **`integrations/base.py`:** an `IntegrationProvider` protocol with these methods: `list_toolkits`, `initiate_connection(user, toolkit, callback_url)`, `handle_callback`, `get_connection_status`, `list_actions(toolkit)`, `get_action_schema`, `execute_action(user, connection, action, args)`, `disconnect`.
3. **`composio_provider.py`:**
   - Uses `COMPOSIO_API_KEY` on the server only.
   - The Composio `user_id` is our internal user id (or a mapping).
   - Callback state is signed (HMAC) and bound to the user.
   - The `integration_connections` table stores only the connection reference and status, never tokens.
4. **Catalog:** an allowlisted set of toolkits (Gmail, Google Sheets, Slack) plus their discovered actions. Adding an app is a config change only.
5. **`integration.action` executor:** config holds toolkit, action and arguments (expressions).
   - Validated against the provider schema before the call.
   - Disconnected or expired connections produce MISSING_CREDENTIALS / AUTH_FAILURE with a "reconnect" suggestion.
   - Side-effect actions are flagged; no auto-retry without idempotency.
6. **Agent tools:** the same provider is exposed through `ai/tools.py`. Only selected actions on connected accounts are offered.
7. **API and UI:**
   - API: `/api/integrations/{toolkits,connections,actions}`, `POST /connect`, the callback route, `DELETE /connections/{id}`.
   - UI: a Connections page, an action picker plus a schema-driven form in the config panel, and connection status badges.
8. **Tests:**
   - Mocked: the provider is faked for authorization, isolation, invalid input, disconnected execution and the agent allowlist.
   - Live (`-m live`): a real Gmail/Sheets/Slack action, which needs your Composio key and an account connected through the UI.
   - If the key is missing, the code is completed up to the boundary and `docs/INTEGRATIONS_SETUP.md` gets exact setup steps.

## MILESTONE 4 — Reliability, debugging, finish (NOT AUTHORIZED YET)
- **Idempotency:** each side-effect node attempt gets the key `execution_id:node_id:attempt-group`, which is passed to the provider where supported. Unsafe retries are blocked, and a retry after an unknown result is reported as "outcome unknown — manual check".
- **Pause, approval and resume:**
  - A `waiting` node status plus an `approvals` table, and the execution moves to `paused`.
  - Endpoints: `POST /api/approvals/{id}/approve|reject`.
  - The runner resumes from persisted node state; the agent resumes through the LangGraph checkpoint and `interrupt`.
- **Restart recovery:** paused executions survive a restart, and running executions are marked interrupted. Resume is offered only at safe checkpoints.
- **Cancellation:** wired through to the UI.
- **Diagnostics:** an error panel showing node, operation, category, explanation, field, suggestion and correlation id. A "copy debug bundle" exports a redacted export of the execution.
- **Live updates:** Server-Sent Events replace polling if that proves cleaner; polling stays as the fallback.
- **UI:** glass design refinement and performance (memoized nodes, large-graph check).
- **Tests:** acceptance tests 1–10, plus the full regression suite.

## Environment variables (cumulative)
- **Existing:** `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_REVIEWER_MODEL`, `MAX_GENERATION_RETRIES`, `MAX_REVIEW_CORRECTION_ATTEMPTS`, `ENABLE_WORKFLOW_REVIEW`, `MOCK_DEV_MODE`, `CORS_ORIGINS`
- **Milestone 1:** `DATABASE_URL` (default `sqlite+aiosqlite:///./agentic_flow.db`), `JWT_SECRET`, `JWT_EXPIRES_MINUTES`, `CREDENTIALS_ENCRYPTION_KEY`, `HTTP_ALLOW_PRIVATE_NETWORKS`, `PUBLIC_BASE_URL`
- **Milestone 2:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- **Milestone 3:** `COMPOSIO_API_KEY`, `COMPOSIO_AUTH_CONFIG_{GMAIL,SHEETS,SLACK}` (if the SDK requires them)
- **Frontend:** `NEXT_PUBLIC_API_URL`

## Verification (each milestone)
- **Backend:** `cd backend && python -m pytest -q` (mocked, deterministic), `python -m pytest -m live` (real providers, when keys exist), `ruff check app tests`, `mypy app` (gradual).
- **Frontend:** `cd frontend && npm run lint && npm run typecheck && npm test && npm run build`.
- **End-to-end manual check:**
  1. `uvicorn app.main:app --reload` plus `npm run dev`
  2. Register, then build the demo workflow on the canvas
  3. Save, reload, Validate
  4. Run, then watch real statuses and inspect node I/O
  5. Generate a workflow with AI, then run it
  6. Once Milestone 2 is done, run an Agent workflow with a live key
- After each milestone: update `IMPLEMENTATION_STATUS.md` with files changed, capabilities, tests run and results, blockers, and the next step. Commit to `testing` locally; never push without confirmation.

## Risks and notes
- Python 3.13 wheels for LangChain, LangGraph and Composio must be checked in Milestone 2/3. If a package is incompatible, the plan pins compatible versions or documents a 3.12 venv.
- Model IDs in the brief and in `.env` (`gemini-3.8-flash`, `gemma-4-31b-it`, …) are verified live before they are relied on. Unverifiable IDs stay configurable and are never hardcoded as guaranteed.
- The in-process runner is simple but doesn't survive a restart mid-node. That limitation is documented, and the schema leaves room for a queue later.
