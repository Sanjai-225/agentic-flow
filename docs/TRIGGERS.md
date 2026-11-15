# Triggers and flow nodes (Milestone 2)

## Workflow activation
- **Toolbar switch.** Every saved workflow has an **Active** switch in the editor toolbar (`PATCH /api/workflows/{id}/active`).
- **Inactive workflows** ignore webhook calls (409), public form submissions (the form is offline, 404) and schedules (never fired). Manual runs always work.
- **Defaults.** Existing workflows were migrated as active, so Milestone 1 webhooks keep working.

## Form Submission Trigger (`core.form_trigger`)
1. **Build the form.** Add the node and configure the title, description, fields, submit label and success message.
   - **Field types:** text, email, number, textarea, select, checkbox.
   - **Per-field options:** required, placeholder, options (select), min/max (number) and max length.
2. **Publish.** Save the workflow. The backend creates a public form id: `frm_` + 128 random bits, stable across saves.
3. **Share.** The node panel shows the public URL `{PUBLIC_APP_URL}/forms/{form_id}`, with *Copy*, *Open preview* and *New URL*. *New URL* rotates the id; the old one stops working at once.

### Public endpoint protections
| | Endpoint / behaviour |
|---|---|
| Definition | `GET /api/public/forms/{id}` returns only title, description, fields, submit label and the honeypot field name. Never the workflow, nodes, owner or config. |
| Submit | `POST /api/public/forms/{id}` with `{"data": {...}, "_hp": ""}`, JSON only (415 otherwise) |
| Body size | Capped by `FORM_MAX_BODY_BYTES` (413) |
| Rate limits | Per client IP (`FORM_RATE_LIMIT_PER_MINUTE`) and per form (×10) (429). In-memory per worker; see the limitations below. |
| Honeypot | A filled honeypot gets a normal success response but no run |
| Validation | On the server: types, required, email syntax, number range, select options, length, unknown fields → 422 with field errors |
| Unavailable | An unknown or rotated id, a disabled form, an inactive workflow or a removed node all return the same 404 |
| Not runnable | A workflow that fails validation returns 503 to the public; the owner sees the problems in the editor |

### Run output
- **Success.** The endpoint responds `202 {"ok": true, "message": <success message>}`. No execution ids or internal errors are returned.
- **Trigger output:**
  ```json
  {"submission": {"name": "Ada", "email": "ada@example.com", "budget": 5000, "consent": true},
   "submitted_at": "2026-11-15T12:00:00+00:00", "form_id": "frm_…"}
  ```
- **Typing.** The submission contains exactly the configured fields: numbers are numbers, checkboxes are booleans, empty optional fields are null.
- **Manual test runs** produce the same shape with `test_run: true`.

## Schedule Trigger (`core.schedule_trigger`)
- **Modes:**

  | Mode | Fields |
  |---|---|
  | `interval` | `interval_minutes`, at least `SCHEDULE_MIN_INTERVAL_MINUTES` |
  | `hourly` | `minute` |
  | `daily` | `hour`, `minute` |
  | `weekdays` | Mon–Fri at `hour`:`minute` |
  | `weekly` | `weekdays` [mon..sun] |
  | `cron` | 5-field expression, validated, no more often than the minimum interval |

  Plus `timezone` (an IANA zone; DST-aware), `enabled` and `misfire_policy` (`skip` | `run_once`).
- **Preview.** `POST /api/workflows/schedule-preview` validates a config and returns the next run times. The node panel shows them live.
- **Persistence.** Saving the workflow upserts `workflow_schedules` (one row per trigger node). Removing the trigger removes the schedule. An unchanged spec keeps its `next_run_at`.
- **Scheduler** (`engine/scheduler.py`): a database-driven asyncio loop started with the app (`SCHEDULER_ENABLED`, `SCHEDULER_POLL_SECONDS`). For each due schedule whose workflow is active, it:
  1. applies the misfire policy if the occurrence is more than about 60 s overdue (after downtime): `skip` drops it, `run_once` runs one catch-up. A backlog is never replayed;
  2. claims the occurrence by inserting `schedule_occurrences(schedule_id, scheduled_for)`. The **unique constraint** guarantees one run per occurrence, even with several workers;
  3. re-plans the current version for the owner and creates an execution with `trigger_type=schedule` and payload `{schedule_id, scheduled_for, fired_at, timezone, workflow_id, catch_up}`;
  4. advances `next_run_at`, keeping the phase for interval schedules.
- **Status.** `GET /api/workflows/{id}/schedules` returns enabled, next run, last run, last execution id and status, last error, and the upcoming runs.
- **Restarts.** Rows persist, so a restarted process resumes polling, and overdue rows go through the misfire policy.

## Switch, Merge, Loop Over Items
- **Switch** (`core.switch`):
  - Cases `{key, label, conditions}` use the same typed comparison rules as If/Else.
  - **Outputs:** one output port per case key, plus `default`. The editor and the planner derive the ports from the config in the same way (`DynamicPorts`).
  - **Routing:** `first` takes the first match; `all` takes every match.
  - **Trace:** the selected route and every case evaluation are recorded.
- **Merge** (`core.merge`):
  - **Inputs:** `input_1..input_N` (2–5). Every input must be connected.
  - **Modes:** `by_input` → `{input_1: …}`; `append` → `{items, count}`; `merge_objects` → one object.
  - **Requirement:** `require: all` fails with `MISSING_INPUT` when a connected branch did not run; `any` merges whatever arrived (use it after If/Switch).
  - **Semantics:** *sequential synchronisation*. The engine runs nodes one at a time in topological order, so Merge runs exactly once, after every predecessor has finished or been skipped. There is no parallel execution.
- **Loop Over Items** (`core.loop`):
  - **Ports:**
    - Nodes reachable from the `item` port form the **body**. The body runs once per element, with `{{item…}}` and `{{loop.index}}`, `{{loop.count}}`, `{{loop.is_first}}`, `{{loop.is_last}}` available.
    - After the last item, the `done` port continues with `{results, count, succeeded, failed, errors, items}`. `results[i]` is the output of the body's terminal node for item `i`.
  - **Bounds:** `max_items` (and `LOOP_MAX_ITEMS`) and `timeout_seconds`.
  - **Errors:** `on_item_error: stop|continue`.
  - **Body execution:** body nodes run through the normal node runner (retries, timeouts, persistence). Their history keeps the last iteration plus a per-iteration summary (first 100).
  - **Planner rules:**
    - body nodes cannot connect outside the body;
    - triggers, End nodes and nested loops are not allowed in a body;
    - nodes outside the loop cannot reference body nodes (use `…loop.output.results`);
    - `item`/`loop` are only valid inside a body.
- **Date & Time** (`core.datetime`) and **Array** (`core.array`): pure, bounded data operations. See the node descriptions in the editor.
