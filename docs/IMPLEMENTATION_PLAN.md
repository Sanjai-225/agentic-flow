# Implementation Plan (summary)

The full plan, including requirements, architecture and acceptance criteria, is in [`MASTER_IMPLEMENTATION_PLAN.md`](MASTER_IMPLEMENTATION_PLAN.md). Progress is tracked in [`IMPLEMENTATION_PROGRESS.md`](IMPLEMENTATION_PROGRESS.md). Each milestone requires separate authorization.

| # | Milestone | Scope | Key deliverables |
|---|---|---|---|
| 1 | Core executable engine | Baseline restore, canonical schema v2, registry, executor contract, 9 executable operations, planner, sequential runner, persistence, auth, credentials, webhook ingress, editor/execution UI | Demo workflow (Manual → Set → If → HTTP → End) runs end to end with real backend state |
| 2 | Universal AI and Agent node | Provider catalog (verified model IDs), `ai.llm_generate`, `ai.extract`, `ai.agent` on LangChain/LangGraph, tool registry with backend authorization, traces | Live provider tests per adapter |
| 3 | Composio integrations | `IntegrationProvider` protocol, Composio provider, user-scoped connections, action discovery and schemas, `integration.action`, agent tools | Real Gmail/Sheets/Slack action once keys and accounts are provided |
| 4 | Reliability and finish | Idempotency keys, approvals, pause/resume from checkpoints, restart recovery, diagnostics bundle, SSE, UI refinement | Approval pause/resume, restart persistence, full regression |

## Extension points Milestone 1 leaves for later milestones
- Registry fields `credentials`, `side_effects`, `idempotent`, `requires_approval`, `supports_streaming`, `is_async`.
- Status enums `paused` (workflow) and `waiting` (node), already in the API contract.
- Encrypted `credentials` table and the `CredentialAccessor` protocol, for provider keys and connections.
- A new node type plugs in as config model + definition + executor. The runner and planner do not change.
- `ExecutionContext.resolve`, which lets executors evaluate expressions lazily (used by Filter; agent tools later).
