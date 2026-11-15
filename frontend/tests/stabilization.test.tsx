/* Regression tests for the Milestone 1 fix list (Milestone 2, Phase 0):
 * (a) predictable node ids, (b) data fields before the first run, (e) structured error text,
 * (f) JSON editors that keep references typed. */

import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  JsonTemplateEditor,
  KeyValueEditor,
  formatJsonTemplate,
  parseJsonTemplate,
  parseTemplateValue,
  quoteBareReferences,
} from '@/components/editor/fields';
import { pickerPaths } from '@/components/editor/NodeConfigPanel';
import { api } from '@/lib/api';
import { uniqueNodeId } from '@/lib/workflowMapping';

import { definition } from './fixtures';

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('(a) predictable node ids', () => {
  const set = definition({ operation_id: 'core.set', id_prefix: 'set' });
  const http = definition({ operation_id: 'http.request', id_prefix: 'http' });

  it('starts at 1 regardless of how many other nodes exist', () => {
    expect(uniqueNodeId(set, new Set(['manual_trigger_1', 'if_1', 'end_1']))).toBe('set_1');
  });

  it('uses the smallest free number and the registry id prefix', () => {
    expect(uniqueNodeId(set, new Set(['set_1', 'set_3']))).toBe('set_2');
    expect(uniqueNodeId(http, new Set(['set_1']))).toBe('http_1');
  });

  it('falls back to the last operation segment without an id_prefix', () => {
    expect(uniqueNodeId(definition({ operation_id: 'core.json_parse', id_prefix: null }), new Set())).toBe('json_parse_1');
  });
});

describe('(f) JSON templates keep references typed', () => {
  it('quotes bare references but never touches references inside strings', () => {
    expect(quoteBareReferences('{"a": {{nodes.set_1.output.n}}, "b": "x {{trigger.y}}"}')).toBe(
      '{"a": "{{nodes.set_1.output.n}}", "b": "x {{trigger.y}}"}',
    );
    expect(quoteBareReferences('{"k": {{nodes.x.output["odd key"]}}}')).toBe('{"k": "{{nodes.x.output[\\"odd key\\"]}}"}');
  });

  it('parses objects, arrays and scalars instead of storing them as text', () => {
    expect(parseJsonTemplate('{"amount": {{nodes.set_1.output.amount}}, "tags": [1, {{trigger.t}}], "ok": true}')).toEqual({
      ok: true,
      value: { amount: '{{nodes.set_1.output.amount}}', tags: [1, '{{trigger.t}}'], ok: true },
    });
    expect(parseJsonTemplate('{{nodes.set_1.output}}')).toEqual({ ok: true, value: '{{nodes.set_1.output}}' });
    expect(parseJsonTemplate('42')).toEqual({ ok: true, value: 42 });
    expect(parseJsonTemplate('Total {{nodes.set_1.output.amount}}')).toEqual({ ok: true, value: 'Total {{nodes.set_1.output.amount}}' });
    expect(parseJsonTemplate('   ')).toEqual({ ok: true, value: null });
  });

  it('reports malformed objects instead of silently saving a string', () => {
    const res = parseJsonTemplate('{"a": }');
    expect(res.ok).toBe(false);
  });

  it('round-trips stored values through the editor text', () => {
    const values: unknown[] = [
      { amount: '{{nodes.set_1.output.amount}}', note: 'Hi {{trigger.name}}', n: [1, 2], nested: { x: null } },
      '{{nodes.http_1.output.body}}',
      'plain text',
      '42',
      'true',
      42,
      [1, '{{trigger.a}}'],
      { odd: '{{nodes.x.output["odd key"]}}' },
    ];
    for (const value of values) {
      const parsed = parseJsonTemplate(formatJsonTemplate(value));
      expect(parsed).toEqual({ ok: true, value });
    }
    expect(formatJsonTemplate({ a: '{{nodes.set_1.output.a}}' }, false)).toBe('{"a":{{nodes.set_1.output.a}}}');
  });

  it('single-line values: incomplete JSON stays text while typing, then becomes typed', () => {
    expect(parseTemplateValue('{"a":')).toBe('{"a":');
    expect(formatJsonTemplate('{"a":', false)).toBe('{"a":');
    expect(parseTemplateValue('{"a": 1}')).toEqual({ a: 1 });
    expect(parseTemplateValue('')).toBe('');
  });

  it('JsonTemplateEditor commits typed JSON on blur and rejects invalid objects', () => {
    const onChange = vi.fn();
    render(<JsonTemplateEditor ariaLabel="Final output" value={null} onChange={onChange} />);
    const box = screen.getByLabelText('Final output');
    fireEvent.change(box, { target: { value: '{"total": {{nodes.set_1.output.amount}}, "items": [1]}' } });
    fireEvent.blur(box);
    expect(onChange).toHaveBeenLastCalledWith({ total: '{{nodes.set_1.output.amount}}', items: [1] });

    onChange.mockClear();
    fireEvent.change(box, { target: { value: '{"total": ' } });
    fireEvent.blur(box);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/Invalid JSON/)).toBeInTheDocument();
  });

  it('KeyValueEditor in JSON mode stores objects and numbers, not strings', () => {
    function Harness() {
      const [v, setV] = useState<Record<string, unknown>>({ total: '' });
      return (
        <>
          <KeyValueEditor value={v} onChange={setV} jsonValues />
          <pre data-testid="state">{JSON.stringify(v)}</pre>
        </>
      );
    }
    render(<Harness />);
    fireEvent.change(screen.getByLabelText('value'), { target: { value: '{"a": 1, "b": {{trigger.b}}}' } });
    expect(JSON.parse(screen.getByTestId('state').textContent!)).toEqual({ total: { a: 1, b: '{{trigger.b}}' } });
    fireEvent.change(screen.getByLabelText('value'), { target: { value: '7' } });
    expect(JSON.parse(screen.getByTestId('state').textContent!)).toEqual({ total: 7 });
  });
});

describe('(b) data picker before the first run', () => {
  it('offers backend-inferred fields when the node has not run', () => {
    const paths = pickerPaths('set_1', undefined, {
      source: 'config',
      fields: [{ path: '.amount', expr: '{{nodes.set_1.output.amount}}' }],
    });
    expect(paths.map((p) => p.expr)).toEqual(['{{nodes.set_1.output}}', '{{nodes.set_1.output.amount}}']);
    expect(paths[1].preview).toBe('expected, from config');
  });

  it('prefers real outputs after a successful run', () => {
    const paths = pickerPaths('set_1', { status: 'success', output: { real: 1 } }, {
      source: 'config',
      fields: [{ path: '.amount', expr: '{{nodes.set_1.output.amount}}' }],
    });
    expect(paths.map((p) => p.expr)).toEqual(['{{nodes.set_1.output}}', '{{nodes.set_1.output.real}}']);
  });

  it('calls the output-fields endpoint with the definition', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ nodes: {} }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await api.outputFields({ schema_version: 2, workflow_id: 'draft', workflow_name: 'x', nodes: [], edges: [] } as any);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/api/workflows/output-fields');
    expect(init.method).toBe('POST');
  });
});

describe('(e) structured AI designer errors', () => {
  it('shows the message together with the suggested next step', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: { category: 'invalid_api_key', message: 'Gemini rejected the API key.', suggestion: 'Check GEMINI_API_KEY.' } }), { status: 502 }),
      ),
    );
    await expect(api.generate('build something')).rejects.toMatchObject({
      status: 502,
      message: 'Gemini rejected the API key. Check GEMINI_API_KEY.',
      detail: { category: 'invalid_api_key' },
    });
  });
});
