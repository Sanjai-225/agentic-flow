# CLAUDE.md — Agentic Flow

AI-assisted, n8n-inspired workflow builder **and executor**. FastAPI backend (`backend/`), Next.js 14 + React Flow frontend (`frontend/`).

## Process rules
- Work on branch `testing`; `main` is owner-only via PR. Never `git push` or force-push without explicit human confirmation. Never commit `.env`. Do not modify `agent.md`.
- Milestones are authorized one at a time — check `docs/IMPLEMENTATION_PROGRESS.md` before starting work. Plan: `docs/MASTER_IMPLEMENTATION_PLAN.md`. Running record: `IMPLEMENTATION_STATUS.md` (update it after every milestone).
- Never fake execution, integrations or success. Unsupported/unconfigured capabilities must be reported explicitly.

## Architecture boundaries
- **Canonical workflow schema v2** (`backend/app/schemas/workflow.py`) is the single source of truth for the AI designer, the editor and the engine. v1 docs are upgraded by `services/workflow_upgrade.py`. `ui` fields are presentation-only; the engine never reads them.
- **Registry** (`app/registry/`): definitions keyed by stable `operation_id` (`core.set`, `http.request`…); config models in `registry/configs.py`, valid examples in `registry/examples.py`. Design-only types stay registered with `executable=False`.
- **Executors** (`app/executors/`) implement `execute(config, inputs, ctx) -> NodeExecutionResult` (`engine/contracts.py`) and register with `@register`. A node is executable only if the registry marks it executable AND an executor is registered (test-enforced).
- **Engine** (`app/engine/`): `planner.py` validates before every run; `runner.py` is the sequential state machine (branch activation, retries, timeouts, cancellation, per-node persistence); `worker.py` runs executions as in-process asyncio tasks; `expressions.py` resolves `{{nodes.<id>.output.x}}`, `{{trigger.x}}`, `{{input.x}}` with a hand-written parser (never `eval`).
- **AI designer** (`services/llm_service.py`, `workflow_generator.py`, `workflow_reviewer.py`): Gemini generation (REST-first, SDK fallback) + Gemma reviewer. Its output is upgraded to v2 and annotated with `execution_readiness`. Blocking calls run in a threadpool.
- **Persistence**: SQLAlchemy 2 async + aiosqlite, Alembic migrations (`backend/alembic/`, auto-applied on startup). Every user-owned query filters by `user_id`.
- **Frontend**: state in `frontend/store/editorStore.ts` (zustand); canonical↔React Flow in `lib/workflowMapping.ts`; API client `lib/api.ts`. Execution status shown in the UI comes only from backend polling.

## Security constraints
- Secrets never reach the browser, workflow JSON, logs or prompts. Credentials are Fernet-encrypted (`services/credentials.py`) and referenced by id; recorded node inputs are redacted (`engine/redaction.py`).
- HTTP node blocks private/loopback/link-local targets unless `HTTP_ALLOW_PRIVATE_NETWORKS=true`; redirects are re-checked per hop.
- Side-effecting operations are never auto-retried without an idempotency guarantee.
- No LLM-generated code execution.

## Commands
```bash
# backend
cd backend && pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
python -m pytest -q              # deterministic suite (mock Gemini, temp SQLite, local HTTP server)
python -m pytest -m live         # opt-in tests against real external services
python -m ruff check app tests alembic/env.py
python -m alembic revision --autogenerate -m "msg"   # after changing app/db/models.py
# frontend
cd frontend && npm install
npm run dev | npm run lint | npm run typecheck | npm test | npm run build
```

## Conventions
- Errors use `core/errors.py` (`ErrorCategory`, `NodeError`, `NodeExecutionError`) with message, field, retryable and suggestion.
- New node type = config model + definition (with `example_config`) + executor + tests; nothing else in the engine should change.
- Tests: mocked external services in the default suite; real-provider tests marked `@pytest.mark.live`.
- Shell heredocs on this machine collapse backslashes — use the Write/Edit tools for content containing `\n`, `\b`, etc.
