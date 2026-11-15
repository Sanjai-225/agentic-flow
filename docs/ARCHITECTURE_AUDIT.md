# Architecture Audit (pre-Milestone 1)

Audit date: 2026-11-15. Branch `testing` @ `a55435f`, plus local branch `backup-phase2-phase3` @ `74beac0`.

## Repository
| Area | Finding |
|---|---|
| Backend | FastAPI (`backend/app/main.py`), Python 3.13, unpinned `requirements.txt` (fastapi, uvicorn, python-dotenv, pydantic, google-genai) |
| Frontend | Next.js 14 App Router, `@xyflow/react` 12.12.1, Tailwind 3, light theme, a single page |
| Persistence | None |
| Auth | None |
| LangChain / LangGraph / Composio / Anthropic / OpenAI | Not present |
| Tests | `backend/tests/test_workflow.py` (12 tests, mock mode); on the backup branch, also `test_node_registry.py` (36 tests total) |
| Docs | README (design-only philosophy), `agent.md` (git rules), roadmap on the backup branch |

## AI design pipeline
- `services/llm_service.py`: raw REST call first (a workaround for Windows SSL/HTTP2), then the google-genai SDK. On `testing` the chain is `gemini-3-flash-preview` → … with a 12s timeout and no Gemma.
- On the backup branch the chain is `gemini-3.8-flash` → `gemini-3.5-flash-lite` → `gemini-3-flash-preview` (30s). There is a separate Gemma reviewer (`gemma-4-31b-it`), registry-aware prompts, and a reviewer that fails closed. `backend/.env` was already configured for the backup branch.
- `workflow_generator.py`: generate → Pydantic → `GraphValidator` → repair loop → review → correction.

## Schema (v1)
- `node.type` is a free-form string; `tool{name, operation, status}` is design metadata.
- Edges have `label`/`condition`. There are `start_nodes`/`end_nodes`.
- Missing: version, operation id, ports, input mappings, positions.

## Classification
| Status | Items |
|---|---|
| Works | Gemini generation with failover, Pydantic + graph validation, repair loop, Gemma review (backup branch), mock dev mode, read-only canvas, design registry API |
| Partial | Config inspector (backup branch, local-only edits). Frontend edges sent `source_handle`, which the backend did not support |
| Placeholder | `WorkflowToolbar`, `PromptInput`, unused `services/workflowApi.ts`. Tools always `not_connected` |
| Missing | Execution engine, executors, persistence, auth, credentials, save/load, manual connect/edit, execution UI, tests for any of these |
| Defect | `/api/workflows/generate` performed blocking network I/O on the event loop |

## Decisions (confirmed by the owner)
1. Restore `backup-phase2-phase3` into `testing` (fast-forward). Its registry evolves into the executable registry.
2. Use SQLite + SQLAlchemy 2 + Alembic (Postgres-portable).
3. Minimal built-in auth: email/password, Argon2, JWT. All data is scoped by `user_id`.
4. In-process asyncio execution worker, with state persisted after every node transition.

What was implemented on top of this audit is recorded in [`../IMPLEMENTATION_STATUS.md`](../IMPLEMENTATION_STATUS.md).
