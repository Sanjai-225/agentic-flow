/* Milestone 2 UI: dynamic ports, AI model/tool editors, form builder, schedule editor, switch cases,
 * agent trace / loop inspector, credentials dialog and the public hosted form. */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  FormFieldsEditor,
  ModelSelect,
  ScheduleEditor,
  SwitchCasesEditor,
  ToolSelect,
  describeSchedule,
  resetAdvancedFieldCaches,
  schemaProblem,
  slugKey,
} from '@/components/editor/advancedFields';
import { CredentialsDialog } from '@/components/editor/Dialogs';
import { AgentTrace, LoopIterations, NodeDetail } from '@/components/editor/ExecutionPanel';
import { PublicFormView, validateField } from '@/components/PublicFormView';
import { api, pollExecution, publicForms } from '@/lib/api';
import { portsFor } from '@/lib/ports';
import type { AIProviderInfo, NodeExecution } from '@/types/workflow';

import { definition, execution } from './fixtures';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  resetAdvancedFieldCaches();
});

const caps = (temperature: boolean, effort: boolean) => ({
  tool_calling: true, structured_output: true, streaming: true, temperature, reasoning_effort: effort,
  forced_tool_choice: false, usage_reporting: true, context_window: 1_000_000, max_output_tokens: 128_000,
});
const PROVIDERS: AIProviderInfo[] = [
  { id: 'anthropic', label: 'Anthropic', credential_type: 'anthropic_api_key', docs_url: '', platform_key_available: false,
    models: [{ provider: 'anthropic', model: 'claude-opus-5-5', label: 'Claude Opus 5.5', capabilities: caps(false, true), verified: 'docs', recommended: true }] },
  { id: 'gemini', label: 'Google Gemini', credential_type: 'gemini_api_key', docs_url: '', platform_key_available: true,
    models: [{ provider: 'gemini', model: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', capabilities: caps(true, false), verified: 'live', recommended: true }] },
];

describe('dynamic ports (mirror of backend NodeDefinition.ports_for)', () => {
  const sw = definition({ operation_id: 'core.switch', ports_out: ['default'],
    dynamic_ports: { direction: 'out', source: 'list', config_key: 'cases', key_field: 'key', fixed: ['default'], min_count: 1, max_count: 20 } });
  const merge = definition({ operation_id: 'core.merge', ports_in: ['input_1', 'input_2'],
    dynamic_ports: { direction: 'in', source: 'count', config_key: 'inputs', prefix: 'input_', fixed: [], min_count: 2, max_count: 5 } });

  it('derives Switch outputs from case keys plus default', () => {
    expect(portsFor(sw, { cases: [{ key: 'refund' }, { key: 'upgrade' }, { key: 'refund' }] }).out).toEqual(['refund', 'upgrade', 'default']);
  });
  it('derives Merge inputs from the count, clamped', () => {
    expect(portsFor(merge, { inputs: 3 }).in).toEqual(['input_1', 'input_2', 'input_3']);
    expect(portsFor(merge, { inputs: 99 }).in).toHaveLength(5);
    expect(portsFor(merge, {}).in).toEqual(['input_1', 'input_2']);
  });
  it('keeps static ports for ordinary nodes and unknown nodes', () => {
    expect(portsFor(definition({ operation_id: 'core.loop', ports_out: ['item', 'done'] }), {}).out).toEqual(['item', 'done']);
    expect(portsFor(undefined, {})).toEqual({ in: ['main'], out: ['main'] });
  });
});

describe('ModelSelect', () => {
  it('offers verified models, hides unsupported options and filters credentials by provider', async () => {
    vi.spyOn(api, 'aiProviders').mockResolvedValue(PROVIDERS);
    vi.spyOn(api, 'listCredentials').mockResolvedValue([
      { id: 'cred_a', type: 'anthropic_api_key', name: 'Team Anthropic', hints: { api_key: '••••abcd' }, created_at: null },
      { id: 'cred_g', type: 'gemini_api_key', name: 'Gemini key', hints: {}, created_at: null },
    ]);
    function Harness() {
      const [v, setV] = useState<any>(null);
      return (
        <>
          <ModelSelect value={v} onChange={setV} ariaLabel="Primary" />
          <pre data-testid="value">{JSON.stringify(v)}</pre>
        </>
      );
    }
    render(<Harness />);
    await waitFor(() => expect(screen.getByLabelText('Primary provider')).toHaveTextContent('Anthropic'));
    fireEvent.change(screen.getByLabelText('Primary provider'), { target: { value: 'anthropic' } });
    expect(JSON.parse(screen.getByTestId('value').textContent!)).toMatchObject({ provider: 'anthropic', model: 'claude-opus-5-5' });
    await waitFor(() => expect(screen.getByLabelText('Primary credential')).toHaveTextContent('Team Anthropic'));
    expect(screen.getByLabelText('Primary credential')).not.toHaveTextContent('Gemini key');
    expect(screen.queryByLabelText('Primary temperature')).toBeNull(); // Anthropic rejects sampling params
    expect(screen.getByLabelText('Primary reasoning effort')).toBeInTheDocument();
    expect(screen.getByText(/Add a Anthropic API key/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Primary provider'), { target: { value: 'gemini' } });
    expect(screen.getByLabelText('Primary temperature')).toBeInTheDocument();
    expect(screen.getByLabelText('Primary credential')).toHaveTextContent('Platform key');
  });
});

describe('ToolSelect / JSON schema / form builder / switch cases', () => {
  it('toggles an explicit tool allowlist', async () => {
    vi.spyOn(api, 'aiTools').mockResolvedValue([
      { id: 'calculator', name: 'calculator', description: 'math', provider: 'builtin', permission: 'read_only', side_effects: false, timeout_seconds: 5, tags: [] },
      { id: 'http_get', name: 'http_get', description: 'fetch', provider: 'builtin', permission: 'network', side_effects: false, timeout_seconds: 12, tags: [] },
    ]);
    const onChange = vi.fn();
    render(<ToolSelect value={['calculator']} onChange={onChange} />);
    await waitFor(() => expect(screen.getByLabelText('tool http_get')).toBeInTheDocument());
    expect(screen.getByText('network')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('tool http_get'));
    expect(onChange).toHaveBeenLastCalledWith(['calculator', 'http_get']);
    fireEvent.click(screen.getByLabelText('tool calculator'));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('flags unusable output schemas', () => {
    expect(schemaProblem({ type: 'array' })).toMatch(/object/);
    expect(schemaProblem({ type: 'object', properties: {} })).toMatch(/at least one property/);
    expect(schemaProblem({ type: 'object', properties: { a: { type: 'string' } } })).toBeNull();
  });

  it('builds form fields and keeps type-specific keys clean', () => {
    expect(slugKey('Work email!', ['work_email'])).toBe('work_email_2');
    function Harness() {
      const [v, setV] = useState<any[]>([]);
      return (
        <>
          <FormFieldsEditor value={v} onChange={setV} />
          <pre data-testid="fields">{JSON.stringify(v)}</pre>
        </>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByText('+ Add field'));
    fireEvent.change(screen.getByLabelText('form field 1 type'), { target: { value: 'select' } });
    fireEvent.change(screen.getByLabelText('form field 1 options'), { target: { value: 'starter, pro' } });
    fireEvent.click(screen.getByLabelText('form field 1 required'));
    let fields = JSON.parse(screen.getByTestId('fields').textContent!);
    expect(fields[0]).toMatchObject({ key: 'field_1', type: 'select', options: ['starter', 'pro'], required: true });
    fireEvent.change(screen.getByLabelText('form field 1 type'), { target: { value: 'number' } });
    fields = JSON.parse(screen.getByTestId('fields').textContent!);
    expect(fields[0].options).toBeUndefined();
  });

  it('edits switch cases as output ports', () => {
    function Harness() {
      const [v, setV] = useState<any[]>([{ key: 'case_1', conditions: { combinator: 'all', rules: [{ left: '', operator: 'eq', right: '' }] } }]);
      return (
        <>
          <SwitchCasesEditor value={v} onChange={setV} />
          <pre data-testid="cases">{JSON.stringify(v.map((c) => c.key))}</pre>
        </>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByText('+ Add case'));
    fireEvent.change(screen.getByLabelText('case 2 key'), { target: { value: 'Big Spender' } });
    expect(JSON.parse(screen.getByTestId('cases').textContent!)).toEqual(['case_1', 'big_spender']);
  });
});

describe('ScheduleEditor', () => {
  it('shows the backend preview of the next runs and validation errors', async () => {
    const preview = vi.spyOn(api, 'schedulePreview').mockResolvedValue({ valid: true, errors: [], kind: 'cron', expression: '0 9 * * 1-5', next_runs: ['2026-11-16T09:00:00+00:00'] });
    function Harness() {
      const [c, setC] = useState<Record<string, any>>({ mode: 'weekdays', hour: 9, minute: 0, timezone: 'UTC' });
      return <ScheduleEditor config={c} onConfig={setC} />;
    }
    render(<Harness />);
    expect(screen.getByText('Weekdays at 09:00')).toBeInTheDocument();
    await waitFor(() => expect(preview).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('schedule-preview')).toHaveTextContent('2026'));
    preview.mockResolvedValue({ valid: false, errors: ["Unknown time zone 'Mars/X'."], next_runs: [] });
    fireEvent.change(screen.getByLabelText('Time zone'), { target: { value: 'Mars/X' } });
    await waitFor(() => expect(screen.getByText("Unknown time zone 'Mars/X'.")).toBeInTheDocument());
    expect(describeSchedule({ mode: 'interval', interval_minutes: 5 })).toBe('Every 5 minute(s)');
  });
});

describe('execution inspector for AI and loop nodes', () => {
  const agentRun: NodeExecution = {
    node_id: 'agent_1', operation: 'ai.agent', label: 'Agent', position: 1, status: 'success', attempts: 1, inputs: {}, route: null,
    output: { result: { total: 250 } }, error: null, started_at: null, finished_at: null, duration_ms: 1200,
    metadata: {
      ai: { requested: { provider: 'openai', model: 'gpt-6.1-sol' }, provider: 'anthropic', model: 'claude-sonnet-5-5', credential_source: 'user',
            fallback_used: true, fallback_configured: { provider: 'anthropic' }, fallback_reason: 'MODEL_UNAVAILABLE: rate limited', usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 } },
      agent_trace: [
        { type: 'model_call', iteration: 1 },
        { type: 'tool_call', tool: 'calculator', status: 'success', args: { expression: '1+1' }, result_summary: '{"result": 2}', duration_ms: 3 },
        { type: 'tool_call', tool: 'http_get', status: 'rejected', args: { query: { api_key: '***redacted***' } }, reason: 'not enabled' },
      ],
      model_calls: [{ role: 'primary', status: 'error' }, { role: 'fallback', status: 'success' }],
    },
  };

  it('shows requested vs used model, fallback, usage and redacted tool calls', () => {
    render(<AgentTrace node={agentRun} />);
    expect(screen.getByText(/Requested:/)).toHaveTextContent('openai/gpt-6.1-sol');
    expect(screen.getByText(/Used:/)).toHaveTextContent('anthropic/claude-sonnet-5-5');
    expect(screen.getByText(/Fallback reason/)).toHaveTextContent('rate limited');
    expect(screen.getByText(/Tokens:/)).toHaveTextContent('15');
    expect(screen.getByText('calculator')).toBeInTheDocument();
    expect(screen.getByText(/api_key.*redacted/)).toBeInTheDocument();
    expect(screen.getByText(/model reasoning is never stored/)).toBeInTheDocument();
  });

  it('opens the AI tab by default for AI nodes and shows loop iterations', () => {
    render(<NodeDetail node={agentRun} execution={execution('completed', [agentRun])} />);
    expect(screen.getByTestId('agent-trace')).toBeInTheDocument();
    render(<LoopIterations node={{ ...agentRun, node_id: 'set_1', metadata: { loop_id: 'loop_1', iteration_count: 2, iterations: [{ index: 0, status: 'success', output_preview: { a: 1 } }, { index: 1, status: 'failed', error: 'bad' }] } }} />);
    expect(screen.getByText(/#1 failed/)).toBeInTheDocument();
  });
});

describe('credentials dialog', () => {
  it('uses backend type specs, masks keys and runs a real connection test', async () => {
    vi.spyOn(api, 'listCredentials').mockResolvedValue([{ id: 'cred_1', type: 'openai_api_key', name: 'OpenAI', hints: { api_key: '••••9999' }, provider: 'openai', created_at: null }]);
    vi.spyOn(api, 'credentialTypeSpecs').mockResolvedValue([
      { type: 'openai_api_key', label: 'OpenAI API key', fields: ['api_key'], secret_fields: ['api_key'], provider: 'openai', testable: true },
      { type: 'http_bearer', label: 'HTTP Bearer token', fields: ['token'], secret_fields: ['token'], provider: null, testable: false },
    ]);
    const tester = vi.spyOn(api, 'testCredential').mockResolvedValue({ ok: true, message: 'OpenAI accepted the key.', models_available: ['gpt-6.1-sol'] });
    render(<CredentialsDialog onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/••••9999/)).toBeInTheDocument());
    expect((screen.getByLabelText('API key') as HTMLInputElement).type).toBe('password');
    fireEvent.click(screen.getByText('Test'));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('OpenAI accepted the key.'));
    expect(tester).toHaveBeenCalledWith('cred_1');
  });
});

describe('public hosted form', () => {
  const FORM = {
    form_id: 'frm_x', title: 'Project enquiry', description: 'Tell us more', submit_label: 'Send', honeypot_field: '_hp',
    fields: [
      { key: 'email', label: 'Email', type: 'email' as const, required: true },
      { key: 'budget', label: 'Budget', type: 'number' as const, required: true, min: 0 },
      { key: 'consent', label: 'I agree', type: 'checkbox' as const, required: true },
    ],
  };

  it('validates fields like the server does', () => {
    expect(validateField(FORM.fields[0], 'nope')).toMatch(/valid email/);
    expect(validateField(FORM.fields[1], '-1')).toMatch(/at least 0/);
    expect(validateField(FORM.fields[2], false)).toMatch(/must be checked/);
    expect(validateField(FORM.fields[1], '42')).toBeNull();
  });

  it('blocks invalid input, submits valid data and shows server errors', async () => {
    vi.spyOn(publicForms, 'get').mockResolvedValue(FORM);
    const submit = vi.spyOn(publicForms, 'submit')
      .mockResolvedValueOnce({ ok: false, status: 422, message: 'Please correct the highlighted fields.', errors: { email: 'Email must be a valid email address.' } })
      .mockResolvedValueOnce({ ok: true, message: 'Thanks!' });
    render(<PublicFormView formId="frm_x" />);
    await waitFor(() => expect(screen.getByText('Project enquiry')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Send'));
    expect(screen.getByText('Email is required.')).toBeInTheDocument();
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'ada@example.com' } });
    fireEvent.change(screen.getByLabelText(/Budget/), { target: { value: '5000' } });
    fireEvent.click(screen.getByLabelText(/I agree/));
    await act(async () => fireEvent.click(screen.getByText('Send')));
    expect(submit).toHaveBeenCalledWith('frm_x', { email: 'ada@example.com', budget: '5000', consent: true }, '');
    expect(screen.getByText('Email must be a valid email address.')).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByText('Send')));
    expect(screen.getByRole('status')).toHaveTextContent('Thanks!');
  });

  it('shows an unavailable message for unknown or inactive forms', async () => {
    vi.spyOn(publicForms, 'get').mockRejectedValue(new Error('This form is not available.'));
    render(<PublicFormView formId="frm_gone" />);
    await waitFor(() => expect(screen.getByText('Form unavailable')).toBeInTheDocument());
  });

  it('public API never sends the editor token', async () => {
    localStorage.setItem('agentic_flow_token', 'secret-editor-token');
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true, message: 'ok' }), { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    await publicForms.submit('frm_x', { a: 1 }, '');
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.stringify(init.headers)).not.toContain('secret-editor-token');
    localStorage.clear();
  });
});

describe('bounded polling', () => {
  it('stops polling a run that never finishes once the maximum duration passes', async () => {
    const fetcher = vi.fn(async () => execution('paused' as any));
    const final = await pollExecution('exe_1', () => {}, { intervalMs: 1, fetcher, maxDurationMs: 20 });
    expect(final).toBeNull();
    expect(fetcher).toHaveBeenCalled();
  });
});
