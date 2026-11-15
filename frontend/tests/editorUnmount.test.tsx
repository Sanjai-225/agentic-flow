import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';

import { definition } from './fixtures';

vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

beforeAll(() => {
  (globalThis as any).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // Newer Chrome returns a Promise from scroll methods; effects must not return it.
  (Element.prototype as any).scrollIntoView = () => Promise.resolve();
  (globalThis as any).DOMMatrixReadOnly = class {
    m22 = 1;
  };
});

afterEach(() => vi.unstubAllGlobals());

describe('WorkflowEditor lifecycle', () => {
  it('mounts a new workflow, toggles panels and unmounts without effect-cleanup errors', async () => {
    const registry = {
      total_nodes: 2,
      categories: ['input_output', 'data_processing'],
      nodes: [
        definition({ operation_id: 'core.manual_trigger', category: 'input_output', is_trigger: true, ports_in: [] }),
        definition({ operation_id: 'core.set', category: 'data_processing' }),
      ],
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(registry), { status: 200 })));
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...args) => errors.push(args));

    const { default: WorkflowEditor } = await import('@/components/editor/WorkflowEditor');
    const view = render(<WorkflowEditor workflowId={null} />);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    // Close the AI designer (unmounts ChatPanel), reopen it, then unmount everything.
    fireEvent.click(screen.getByLabelText('Close designer'));
    fireEvent.click(screen.getByText('✦ AI Designer'));
    fireEvent.click(screen.getByLabelText('Close designer'));
    view.unmount();
    spy.mockRestore();
    const effectErrors = errors.filter((e) => /destroy is not a function|must not return anything/i.test(String(e)));
    expect(effectErrors).toEqual([]);
  });
});
