import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { summarizeWorkflow } from '@/components/ChatPanel';
import { WorkflowNodeView, legacyTypeOf } from '@/components/CustomNode';
import { NodeDetail } from '@/components/editor/ExecutionPanel';
import { ConditionsEditor, SetFieldsEditor, parseScalar } from '@/components/editor/fields';
import { filterDefinitions, groupDefinitions } from '@/components/editor/NodeLibrary';

import { definition, execution } from './fixtures';

const setNode = { id: 'set_1', type: 'set_variable', operation: 'core.set', label: 'Set Vars', description: '', config: {} };

describe('WorkflowNodeView renders backend execution state', () => {
  it.each([
    ['success', 'Success'],
    ['failed', 'Failed'],
    ['running', 'Running'],
    ['skipped', 'Skipped'],
    ['waiting', 'Waiting'],
    ['pending', 'Pending'],
  ] as const)('shows %s status', (status, label) => {
    render(<WorkflowNodeView node={setNode} definition={definition({ operation_id: 'core.set' })} run={{ status, duration_ms: 12, error: null, attempts: 1 }} />);
    expect(screen.getByTestId('node-set_1')).toHaveAttribute('data-status', status);
    expect(screen.getByTestId('node-status')).toHaveTextContent(label);
  });

  it('shows the real error message for failed nodes', () => {
    render(
      <WorkflowNodeView
        node={setNode}
        definition={definition({ operation_id: 'core.set' })}
        run={{ status: 'failed', duration_ms: 3, attempts: 2, error: { category: 'MISSING_INPUT', message: "'trigger.x' does not exist", retryable: false } }}
      />,
    );
    expect(screen.getByText(/MISSING_INPUT: 'trigger.x' does not exist/)).toBeInTheDocument();
    expect(screen.getByText(/2 attempts/)).toBeInTheDocument();
  });

  it('flags legacy and unknown nodes as not executable, keeping the legacy label', () => {
    const legacy = { node_type: 'llm_agent', label: 'AI Agent / LLM Reasoning (legacy)', category: 'ai_agent', description: 'd', reason: 'r', replacement: 'Use ai.agent' };
    const { rerender } = render(<WorkflowNodeView node={{ ...setNode, operation: 'llm_agent', type: 'llm_agent' }} legacy={legacy} />);
    expect(screen.getByText(/Unsupported legacy node/)).toBeInTheDocument();
    expect(screen.getByText('AI Agent / LLM Reasoning (legacy)')).toBeInTheDocument();
    rerender(<WorkflowNodeView node={{ ...setNode, operation: 'unsupported:ocr' }} />);
    expect(screen.getByText(/Unknown operation \(unsupported:ocr\)/)).toBeInTheDocument();
  });

  it('resolves legacy types from the operation, the unsupported: prefix or the node type', () => {
    const types = { llm_agent: { node_type: 'llm_agent', label: 'L', category: 'ai_agent', description: '', reason: '' } };
    expect(legacyTypeOf({ operation: 'llm_agent', type: 'x' }, types)?.label).toBe('L');
    expect(legacyTypeOf({ operation: 'unsupported:llm_agent', type: 'x' }, types)?.label).toBe('L');
    expect(legacyTypeOf({ operation: 'unsupported:x', type: 'llm_agent' }, types)?.label).toBe('L');
    expect(legacyTypeOf({ operation: 'core.set', type: 'set_variable' }, types)).toBeUndefined();
  });

  it('shows validation problems before a run', () => {
    render(<WorkflowNodeView node={setNode} definition={definition({ operation_id: 'core.set' })} issues={[{ category: 'INVALID_MAPPING', message: 'bad ref', severity: 'error' }]} />);
    expect(screen.getByText(/1 problem: bad ref/)).toBeInTheDocument();
  });
});

describe('Execution inspector', () => {
  it('shows actual output, input and diagnostic error details', () => {
    const exe = execution('failed', [
      {
        node_id: 'http_1',
        label: 'Call API',
        status: 'failed',
        attempts: 1,
        inputs: { config: { url: 'https://api.example.com' } },
        error: { category: 'PROVIDER_ERROR', message: 'The server returned HTTP 404.', retryable: false, field: null, suggestion: 'Check the URL.' },
      },
    ]);
    render(<NodeDetail node={exe.nodes[0]} execution={exe} />);
    const err = screen.getByTestId('node-error');
    expect(err).toHaveTextContent('PROVIDER_ERROR');
    expect(err).toHaveTextContent('HTTP 404');
    expect(err).toHaveTextContent('How to fix: Check the URL.');
    expect(err).toHaveTextContent('corr');
    fireEvent.click(screen.getByRole('button', { name: 'input' }));
    expect(screen.getByText(/api\.example\.com/)).toBeInTheDocument();
  });

  it('explains skipped nodes', () => {
    const exe = execution('completed', [{ status: 'skipped', metadata: { skip_reason: 'No active incoming connection (branch not taken).' } }]);
    render(<NodeDetail node={exe.nodes[0]} execution={exe} />);
    expect(screen.getByText(/branch not taken/)).toBeInTheDocument();
  });
});

describe('config widgets', () => {
  it('ConditionsEditor edits operators and hides the right operand for unary operators', () => {
    function Harness() {
      const [v, setV] = useState<any>({ combinator: 'all', rules: [{ left: '{{trigger.a}}', operator: 'eq', right: 1 }] });
      return (
        <>
          <ConditionsEditor value={v} onChange={setV} />
          <pre data-testid="out">{JSON.stringify(v)}</pre>
        </>
      );
    }
    render(<Harness />);
    expect(screen.getByLabelText('rule 1 right')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('rule 1 operator'), { target: { value: 'is_empty' } });
    expect(screen.queryByLabelText('rule 1 right')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('rule 1 left'), { target: { value: '42' } });
    expect(JSON.parse(screen.getByTestId('out').textContent!).rules[0]).toMatchObject({ left: 42, operator: 'is_empty' });
  });

  it('SetFieldsEditor adds and edits fields', () => {
    function Harness() {
      const [v, setV] = useState<any[]>([]);
      return (
        <>
          <SetFieldsEditor value={v} onChange={setV} />
          <pre data-testid="out">{JSON.stringify(v)}</pre>
        </>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByText('+ Add field'));
    fireEvent.change(screen.getByLabelText('field 1 name'), { target: { value: 'customer.email' } });
    fireEvent.change(screen.getByLabelText('field 1 value'), { target: { value: '{{trigger.email}}' } });
    expect(JSON.parse(screen.getByTestId('out').textContent!)).toEqual([{ name: 'customer.email', value: '{{trigger.email}}', type: 'auto' }]);
  });

  it('parseScalar keeps expressions as text and converts literals', () => {
    expect(parseScalar('100')).toBe(100);
    expect(parseScalar('true')).toBe(true);
    expect(parseScalar('{{trigger.n}}')).toBe('{{trigger.n}}');
    expect(parseScalar('hello')).toBe('hello');
  });
});

describe('node library and designer summary', () => {
  const defs = [
    definition({ operation_id: 'core.set', label: 'Set', tags: ['data'] }),
    definition({ operation_id: 'http.request', label: 'HTTP Request', category: 'tools', tags: ['api'] }),
    definition({ operation_id: 'ai.future', label: 'Future', category: 'brand_new_category' }),
  ];

  it('searches labels, tags and ids (the registry only contains executable nodes)', () => {
    expect(filterDefinitions(defs, '').map((d) => d.operation_id)).toEqual(['core.set', 'http.request', 'ai.future']);
    expect(filterDefinitions(defs, 'api').map((d) => d.operation_id)).toEqual(['http.request']);
    expect(filterDefinitions(defs, 'data')).toHaveLength(1);
  });

  it('groups by category without dropping categories the frontend does not know yet', () => {
    const groups = groupDefinitions(defs).map(([c]) => c);
    expect(groups).toContain('brand_new_category');
    expect(groups.indexOf('tools')).toBeLessThan(groups.indexOf('brand_new_category'));
  });

  it('reports execution readiness honestly for generated workflows', () => {
    const text = summarizeWorkflow({
      workflow_id: 'x',
      workflow_name: 'Gen',
      description: 'd',
      nodes: [{ id: 'a', type: 'trigger', operation: 'unsupported:trigger', label: 'Watch inbox', description: '', config: {}, tool: { name: 'Gmail', operation: 'watch', status: 'not_connected' } }],
      edges: [],
      start_nodes: [],
      end_nodes: [],
      execution_readiness: { executable: false, issues: [{ category: 'UNSUPPORTED_CAPABILITY', severity: 'error', message: "Node 'Watch inbox' has no executable implementation." }] },
    });
    expect(text).toContain('not runnable yet');
    expect(text).toContain('no executable implementation');
  });
});
