/* Helpers for starting runs from the editor and noticing runs started from outside it. */

import type { ExecutionSummary } from '@/types/workflow';

interface FormFieldLike {
  key?: string;
  type?: string;
  options?: string[] | null;
  min?: number | null;
}

/** Example value for one form field, shaped like a real submission. */
function exampleFor(field: FormFieldLike): unknown {
  switch (field.type) {
    case 'email':
      return 'name@example.com';
    case 'number':
      return typeof field.min === 'number' ? field.min : 0;
    case 'checkbox':
      return false;
    case 'select':
      return field.options?.[0] ?? '';
    default:
      return '';
  }
}

/**
 * Pre-filled JSON for the "Run workflow" dialog, based on the workflow's trigger:
 *  - Manual Trigger: its configured sample payload;
 *  - Form Submission Trigger: one entry per form field (a manual run is treated as a test submission and
 *    the values become {{trigger.submission.<key>}});
 *  - other triggers: empty object.
 */
export function runPayloadTemplate(operation: string | null | undefined, config: Record<string, any> | undefined): Record<string, unknown> {
  if (operation === 'core.form_trigger') {
    const fields: FormFieldLike[] = Array.isArray(config?.fields) ? config!.fields : [];
    const out: Record<string, unknown> = {};
    for (const f of fields) if (f?.key) out[f.key] = exampleFor(f);
    return out;
  }
  if (operation === 'core.webhook_trigger') {
    // Same shape as a real webhook call, so {{trigger.body.<field>}} references resolve in test runs.
    return { method: config?.method || 'POST', body: {}, query: {}, headers: {} };
  }
  if (operation === 'core.manual_trigger' && config?.sample_payload && typeof config.sample_payload === 'object') {
    return config.sample_payload;
  }
  return {};
}

/** Help line for the Run dialog: where the payload shows up in expressions. */
export function runPayloadHint(operation: string | null | undefined): string {
  if (operation === 'core.form_trigger')
    return 'Test submission: fill in the form fields. They become {{trigger.submission.<key>}}, exactly like a real form submission.';
  if (operation === 'core.webhook_trigger')
    return 'Simulated webhook call: put the request JSON under "body" (available as {{trigger.body.<field>}}), exactly like a real call.';
  return 'This payload becomes the trigger output, available as {{trigger.<field>}}. The run executes on the backend.';
}

/** Triggers whose runs start outside the editor (public form, webhook, scheduler). */
export const EXTERNAL_TRIGGERS = new Set(['core.form_trigger', 'core.webhook_trigger', 'core.schedule_trigger']);

/** Executions in `rows` that are not in `knownIds` and were not started manually, newest first. */
export function newExternalRuns(knownIds: Set<string>, rows: ExecutionSummary[]): ExecutionSummary[] {
  return rows
    .filter((r) => !knownIds.has(r.id) && r.trigger_type !== 'manual')
    .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')));
}

export const TRIGGER_LABEL: Record<string, string> = {
  form: 'New form submission received',
  webhook: 'New webhook call received',
  schedule: 'Scheduled run started',
};
