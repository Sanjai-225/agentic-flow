'use client';

import { useMemo, useState } from 'react';

import { CATEGORY_COLOR, CATEGORY_LABEL } from '@/lib/status';
import { useEditorStore } from '@/store/editorStore';
import type { NodeDefinition } from '@/types/workflow';

const CATEGORY_ORDER = ['input_output', 'data_processing', 'logic', 'tools', 'ai_agent', 'memory_knowledge', 'human_in_the_loop'];

export function filterDefinitions(defs: NodeDefinition[], query: string, showDesignOnly: boolean): NodeDefinition[] {
  const q = query.trim().toLowerCase();
  return defs.filter((d) => {
    if (!showDesignOnly && !d.executable) return false;
    if (!q) return true;
    return [d.label, d.description, d.operation_id, d.node_type, ...d.tags].some((s) => s.toLowerCase().includes(q));
  });
}

export default function NodeLibrary() {
  const registry = useEditorStore((s) => s.registry);
  const addNode = useEditorStore((s) => s.addNode);
  const [query, setQuery] = useState('');
  const [showDesignOnly, setShowDesignOnly] = useState(false);

  const grouped = useMemo(() => {
    const list = filterDefinitions(registry, query, showDesignOnly);
    const groups: Record<string, NodeDefinition[]> = {};
    list.forEach((d) => (groups[d.category] ||= []).push(d));
    Object.values(groups).forEach((g) => g.sort((a, b) => Number(b.executable) - Number(a.executable) || a.label.localeCompare(b.label)));
    return CATEGORY_ORDER.filter((c) => groups[c]).map((c) => [c, groups[c]] as const);
  }, [registry, query, showDesignOnly]);

  return (
    <aside className="glass flex h-full w-[260px] flex-shrink-0 flex-col rounded-2xl" aria-label="Node library">
      <div className="border-b border-[var(--border)] p-3">
        <p className="mb-2 text-xs font-semibold text-[var(--text-primary)]">Nodes</p>
        <input aria-label="Search nodes" className="field" placeholder="Search nodes…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label className="mt-2 flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
          <input type="checkbox" checked={showDesignOnly} onChange={(e) => setShowDesignOnly(e.target.checked)} />
          Show design-only nodes
        </label>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {grouped.length === 0 && <p className="text-[11px] text-[var(--text-muted)]">No nodes match “{query}”.</p>}
        {grouped.map(([category, defs]) => (
          <div key={category}>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider" style={{ color: CATEGORY_COLOR[category] }}>
              {CATEGORY_LABEL[category] || category}
            </p>
            <div className="space-y-1">
              {defs.map((d) => (
                <button
                  key={d.operation_id}
                  onClick={() => addNode(d)}
                  title={d.executable ? d.description : `${d.description} (design-only: cannot execute yet)`}
                  className={`w-full rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-[var(--surface-hover)] ${d.executable ? '' : 'opacity-50'}`}
                  data-testid={`library-${d.operation_id}`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium text-[var(--text-primary)]">{d.label}</span>
                    {!d.executable && <span className="chip text-[var(--warning)]">design</span>}
                  </span>
                  <span className="block truncate font-mono text-[10px] text-[var(--text-muted)]">{d.operation_id}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
