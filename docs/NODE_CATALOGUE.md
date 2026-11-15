# Node Catalogue

Exact inventory of the backend node registry (`backend/app/registry/`). Phase 0 of Milestone 2 records the baseline below. Phase 1 (node library cleanup) will update the "After" section; it has **not** been applied yet.

## Baseline inventory (Milestone 2, Phase 0, 2026-11-15)

I produced this inventory by loading the live registry (`get_default_registry()`) and checking each operation against the executor registry (`get_executor`).

**Totals: 33 registered types: 9 executable, 24 design-only.** No type is partially implemented: each one either has a registered executor and passes the executable-node tests, or it has no executor at all.

Six older design types are superseded at registration by the executable operations, which now serve them as aliases:

| Older design type | Now an alias of |
|---|---|
| `manual_trigger` | `core.manual_trigger` |
| `webhook_trigger` | `core.webhook_trigger` |
| `data_transform` | `core.transform` |
| `filter` | `core.filter` |
| `condition` | `core.if` |
| `api_call` | `http.request` |

These six are not separate entries in the registry.

### Executable and tested (9) — kept

| operation_id | Label | Category | id_prefix | Evidence |
|---|---|---|---|---|
| `core.manual_trigger` | Manual Trigger | input_output | `manual_trigger` | `test_execution_api.py` (Milestone 1 acceptance) |
| `core.webhook_trigger` | Webhook Trigger | input_output | `webhook_trigger` | `test_webhooks.py` |
| `core.set` | Set Variable / Edit Fields | data_processing | `set` | `test_execution_api.py`, `test_m1_stabilization.py` |
| `core.json_parse` | JSON Parse | data_processing | `json_parse` | `test_registry_executors.py` |
| `core.filter` | Filter | data_processing | `filter` | `test_registry_executors.py` |
| `core.transform` | Transform / Map Fields | data_processing | `transform` | `test_m1_stabilization.py` |
| `core.if` | If / Else | logic | `if` | `test_execution_api.py` (both branches) |
| `core.end` | End | logic | `end` | `test_execution_api.py`, `test_m1_stabilization.py` |
| `http.request` | HTTP Request | tools | `http` | `test_http_node.py` (local server, plus a live httpbin test) |

### Design-only (24): no executor; the planner rejects them before a run

| node_type (= operation) | Label | Category | Why design-only | Milestone 2 plan |
|---|---|---|---|---|
| `schedule_trigger` | Schedule Trigger | input_output | No scheduler exists | Replace with new `core.schedule_trigger` (Phase 5) |
| `email_trigger` | Inbound Email Trigger | input_output | No mail integration | Remove (integrations are Milestone 3) |
| `webhook_output` | HTTP / Webhook Response | input_output | No synchronous response channel | Remove |
| `email_output` | Send Email | input_output | No mail integration | Remove (Milestone 3) |
| `notification_output` | Push Notification / Alert | input_output | No integration | Remove (Milestone 3) |
| `llm_agent` | AI Agent / LLM Reasoning | ai_agent | No model provider layer | Replace with new `ai.agent` (Phase 3) |
| `text_classifier` | Intent & Category Classifier | ai_agent | No model provider layer | Remove; covered by `ai.generate` / `ai.agent` configuration |
| `entity_extractor` | Entity & Data Extractor | ai_agent | No model provider layer | Remove; covered by `ai.generate` with an output schema |
| `summarizer` | Document & Text Summarizer | ai_agent | No model provider layer | Remove; covered by `ai.generate` |
| `database_query` | Database Query (Read) | tools | No database connector | Remove |
| `database_update` | Database Write / Mutate | tools | No database connector | Remove |
| `file_operation` | File & Document Storage | tools | No storage connector | Remove |
| `tool_integration` | External Service Tool | tools | No integrations | Remove (Composio in Milestone 3) |
| `switch` | Multi-Way Switch / Router | logic | Runner has no multi-port routing node | Replace with new `core.switch` (Phase 6) |
| `loop` | Loop / For-Each Iterator | logic | Planner rejects cycles; no per-item sub-run | Replace with new `core.loop` (Phase 6) |
| `error_handler` | Error / Exception Handler | logic | No error routes | Remove |
| `code_execution` | Custom Script Execution | data_processing | Arbitrary code execution is forbidden | Remove permanently |
| `vector_search` | Vector Semantic Search | memory_knowledge | No vector store | Remove |
| `knowledge_retrieval` | Knowledge Base Lookup | memory_knowledge | No knowledge store | Remove |
| `human_approval` | Human-in-the-Loop Approval | human_in_the_loop | No durable pause/resume | Remove (Milestone 4) |
| `merge` | Merge | data_processing | No merge semantics | Replace with new `core.merge` (Phase 6) |
| `wait` | Wait | logic | No durable waits | Remove (Milestone 4) |
| `parallel_branch` | Parallel Branch | logic | The engine is sequential | Remove |
| `join` | Join | logic | The engine is sequential | Remove |

**Planned removal count for Phase 1: all 24 design-only types.** Saved workflows that contain them keep their original operation id, config and edges, and are marked unsupported (see the plan, Phase 1).

### New nodes planned for Milestone 2 (not yet implemented)
- `ai.generate`
- `ai.agent`
- `core.form_trigger`
- `core.schedule_trigger`
- `core.switch`
- `core.merge`
- `core.loop`
- `core.datetime`
- `core.array`

## After cleanup (Milestone 2, final)

- **Removed:** all **24** design-only types were removed from the active registry. Their labels, reasons and replacement advice live in `backend/app/registry/legacy.py`, which is data only and also served by `GET /api/registry/legacy`.
- **Preserved:** the 9 Milestone 1 operations, with unchanged operation ids and behaviour.
- **Added:** 9 new executable operations.
- **Active library:** 18 operations. Every one has a config model, an executor, UI fields, an example config and tests.

| operation_id | Label | Category | Status | Key tests |
|---|---|---|---|---|
| `core.manual_trigger` | Manual Trigger | input_output | existing | `test_execution_api.py` |
| `core.webhook_trigger` | Webhook Trigger | input_output | existing (now honours the workflow active flag and is rate-limited) | `test_webhooks.py`, `test_triggers.py` |
| `core.form_trigger` | Form Submission Trigger | input_output | **new** | `test_triggers.py` |
| `core.schedule_trigger` | Schedule Trigger | input_output | **new** | `test_triggers.py` |
| `core.set` | Set Variable / Edit Fields | data_processing | existing | `test_m1_stabilization.py` |
| `core.json_parse` | JSON Parse | data_processing | existing | `test_registry_executors.py` |
| `core.filter` | Filter | data_processing | existing | `test_registry_executors.py` |
| `core.transform` | Transform / Map Fields | data_processing | existing | `test_m1_stabilization.py` |
| `core.merge` | Merge | data_processing | **new** | `test_flow_nodes.py` |
| `core.datetime` | Date & Time | data_processing | **new** | `test_flow_nodes.py` |
| `core.array` | Array Operations | data_processing | **new** | `test_flow_nodes.py` |
| `core.if` | If / Else | logic | existing | `test_execution_api.py` |
| `core.switch` | Switch | logic | **new** | `test_flow_nodes.py` |
| `core.loop` | Loop Over Items | logic | **new** | `test_flow_nodes.py` |
| `core.end` | End | logic | existing | `test_execution_api.py` |
| `http.request` | HTTP Request | tools | existing | `test_http_node.py` |
| `ai.generate` | AI Generate | ai_agent | **new** | `test_ai_nodes.py`, `test_ai_live.py` |
| `ai.agent` | AI Agent | ai_agent | **new** | `test_ai_nodes.py`, `test_ai_live.py` |

### Legacy workflow compatibility
- **Saved workflows are untouched.** A workflow saved before Milestone 2 keeps its original operation (e.g. `llm_agent`), `type`, config and connections.
- **v1 documents.** Removed types are upgraded to `unsupported:<type>`, checked against the legacy list first. They are **never** mapped to a new operation, not even when a similarly named node exists (e.g. legacy `switch` → `core.switch`).
- **Planner.** It rejects such nodes before a run with `UNSUPPORTED_CAPABILITY`. The message names the removed type and explains why it was removed. The suggestion names a replacement and states that config and connections are preserved.
- **Editor.** It shows the node as "Unsupported legacy node" with its legacy label. Its original configuration remains readable and editable as raw JSON, so the user can replace the node by hand.
- **Tests:** `test_legacy_workflows.py` and `test_workflow_upgrade.py::test_removed_node_types_are_preserved_never_remapped`.
