import { describe, expect, it } from 'vitest';

import { ancestorsOf, autoLayout, canonicalToFlow, flowToCanonical, outputPaths } from '@/lib/workflowMapping';

import { demoDefinition } from './fixtures';

describe('canonical <-> React Flow mapping', () => {
  it('round-trips nodes, config, ports, settings and positions without loss', () => {
    const { nodes, edges } = canonicalToFlow(demoDefinition);
    expect(nodes.find((n) => n.id === 'http')!.position).toEqual({ x: 600, y: -80 });
    expect(edges.find((e) => e.id === 'e2')!.sourceHandle).toBe('true');

    const back = flowToCanonical({ workflowId: 'wf_1', name: 'Demo', description: 'desc', version: 3 }, nodes, edges);
    expect(back.nodes).toEqual(demoDefinition.nodes);
    expect(back.edges.map(({ id, source, target, source_port, target_port }) => ({ id, source, target, source_port, target_port }))).toEqual(
      demoDefinition.edges.map(({ id, source, target, source_port, target_port }) => ({ id, source, target, source_port, target_port })),
    );
    expect(back.schema_version).toBe(2);
    expect(back.start_nodes).toEqual([]); // derived by the backend
  });

  it('auto-lays out AI-generated definitions without positions (left to right)', () => {
    const noPositions = { ...demoDefinition, nodes: demoDefinition.nodes.map(({ ui, ...n }) => n) };
    const { nodes } = canonicalToFlow(noPositions);
    const x = Object.fromEntries(nodes.map((n) => [n.id, n.position.x]));
    expect(x.trigger).toBeLessThan(x.check);
    expect(x.check).toBeLessThan(x.http);
    expect(x.http).toBe(x.end);
  });

  it('handles cycles and orphans in layout', () => {
    const pos = autoLayout({
      nodes: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] as any,
      edges: [
        { id: '1', source: 'a', target: 'b' },
        { id: '2', source: 'b', target: 'a' },
      ],
    });
    expect(Object.keys(pos).sort()).toEqual(['a', 'b', 'c']);
  });

  it('flattens real outputs into reference expressions', () => {
    const paths = outputPaths('http_1', { status_code: 200, body: { items: [{ id: 1 }] }, 'odd key': 1 });
    const exprs = paths.map((p) => p.expr);
    expect(exprs).toContain('{{nodes.http_1.output}}');
    expect(exprs).toContain('{{nodes.http_1.output.status_code}}');
    expect(exprs).toContain('{{nodes.http_1.output.body.items[0].id}}');
    expect(exprs).toContain('{{nodes.http_1.output["odd key"]}}');
  });

  it('computes upstream ancestors for the data picker', () => {
    const { edges } = canonicalToFlow(demoDefinition);
    expect(ancestorsOf('http', edges).sort()).toEqual(['check', 'trigger']);
    expect(ancestorsOf('trigger', edges)).toEqual([]);
  });
});
