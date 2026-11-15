import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EXAMPLE_PROMPTS } from '@/components/ChatPanel';
import { ExpressionInput, FIELD_DRAG_MIME, referenceDropHandler } from '@/components/editor/fields';
import { newExternalRuns, runPayloadHint, runPayloadTemplate } from '@/lib/runHelpers';
import type { ExecutionSummary } from '@/types/workflow';

describe('runPayloadTemplate', () => {
  it('pre-fills one entry per form field with a typed example', () => {
    const tpl = runPayloadTemplate('core.form_trigger', {
      fields: [
        { key: 'topic', type: 'text' },
        { key: 'email', type: 'email' },
        { key: 'budget', type: 'number', min: 10 },
        { key: 'plan', type: 'select', options: ['basic', 'pro'] },
        { key: 'agree', type: 'checkbox' },
        { key: '', type: 'text' },
      ],
    });
    expect(tpl).toEqual({ topic: '', email: 'name@example.com', budget: 10, plan: 'basic', agree: false });
    expect(runPayloadHint('core.form_trigger')).toContain('{{trigger.submission.<key>}}');
  });

  it('uses the webhook request shape and the manual sample payload', () => {
    expect(runPayloadTemplate('core.webhook_trigger', { method: 'POST' })).toEqual({ method: 'POST', body: {}, query: {}, headers: {} });
    expect(runPayloadTemplate('core.manual_trigger', { sample_payload: { name: 'Ada' } })).toEqual({ name: 'Ada' });
    expect(runPayloadTemplate('core.schedule_trigger', {})).toEqual({});
    expect(runPayloadTemplate(null, undefined)).toEqual({});
  });
});

describe('newExternalRuns', () => {
  const row = (id: string, trigger_type: string, created_at: string) => ({ id, trigger_type, created_at }) as unknown as ExecutionSummary;
  it('returns unseen non-manual runs, newest first', () => {
    const rows = [row('a', 'form', '2026-11-16T10:00:00Z'), row('b', 'manual', '2026-11-16T10:01:00Z'),
      row('c', 'webhook', '2026-11-16T10:02:00Z'), row('d', 'form', '2026-11-16T09:00:00Z')];
    expect(newExternalRuns(new Set(['d']), rows).map((r) => r.id)).toEqual(['c', 'a']);
  });
});

describe('drag and drop of data fields', () => {
  it('inserts the dropped reference at the caret when the browser does not insert it', async () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    render(<ExpressionInput value="Hello " onChange={onChange} ariaLabel="greeting" />);
    const input = screen.getByLabelText('greeting') as HTMLInputElement;
    input.setSelectionRange(6, 6);
    fireEvent.drop(input, { dataTransfer: { getData: (t: string) => (t === FIELD_DRAG_MIME ? '{{trigger.name}}' : '') } });
    vi.runAllTimers();
    expect(onChange).toHaveBeenCalledWith('Hello {{trigger.name}}');
    vi.useRealTimers();
  });

  it('ignores drops that are not data fields', () => {
    const apply = vi.fn();
    const handler = referenceDropHandler(() => null, apply);
    handler({ dataTransfer: { getData: () => '' } } as any);
    expect(apply).not.toHaveBeenCalled();
  });
});

describe('designer starter prompts', () => {
  it('lists titled, described scenarios that only name executable operations', () => {
    expect(EXAMPLE_PROMPTS.length).toBeGreaterThanOrEqual(5);
    for (const p of EXAMPLE_PROMPTS) {
      expect(p.title && p.description && p.prompt).toBeTruthy();
      expect(p.prompt).not.toMatch(/approval|payment|scrap/i); // capabilities that do not exist yet
    }
  });
});
