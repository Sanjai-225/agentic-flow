'use client';

import { useMemo, useState } from 'react';

import { categoryColor, categoryLabel, orderCategories } from '@/lib/status';
import { useEditorStore } from '@/store/editorStore';
import type { NodeDefinition } from '@/types/workflow';

/**
 * Search the active node library. The backend registry only contains executable operations
 * (design-only types were removed in Milestone 2), so there is nothing to hide here.
 */
export function filterDefinitions(defs: NodeDefinition[], query: string): NodeDefinition[] {
  const q = query.trim().toLowerCase();
  if (!q) return defs;
  return defs.filter((d) => [d.label, d.description, d.operation_id, d.node_type, ...d.tags].some((s) => s.toLowerCase().includes(q)));
}

export function groupDefinitions(defs: NodeDefinition[]): [string, NodeDefinition[]][] {
  const groups: Record<string, NodeDefinition[]> = {};
  defs.forEach((d) => (groups[d.category] ||= []).push(d));
  Object.values(groups).forEach((g) => g.sort((a, b) => Number(b.is_trigger) - Number(a.is_trigger) || a.label.localeCompare(b.label)));
  return orderCategories(Object.keys(groups)).map((c) => [c, groups[c]]);
}

export default function NodeLibrary() {
  const registry = useEditorStore((s) => s.registry);
  const addNode = useEditorStore((s) => s.addNode);
  const [query, setQuery] = useState('');

  const grouped = useMemo(() => groupDefinitions(filterDefinitions(registry, query)), [registry, query]);

  return (
    <aside className="glass flex h-full w-[260px] flex-shrink-0 flex-col rounded-2xl" aria-label="Node library">
      <div className="border-b border-[var(--border)] p-3">
        <p className="mb-2 text-xs font-semibold text-[var(--text-primary)]">Nodes</p>
        <input aria-label="Search nodes" className="field" placeholder="Search nodes…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {grouped.length === 0 && <p className="text-[11px] text-[var(--text-muted)]">No nodes match “{query}”.</p>}
        {grouped.map(([category, defs]) => (
          <div key={category}>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider" style={{ color: categoryColor(category) }}>
              {categoryLabel(category)}
            </p>
            <div className="space-y-1">
              {defs.map((d) => (
                <button
                  key={d.operation_id}
                  onClick={() => addNode(d)}
                  title={d.description}
                  className="w-full rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-[var(--surface-hover)]"
                  data-testid={`library-${d.operation_id}`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium text-[var(--text-primary)]">{d.label}</span>
                    {d.is_trigger && <span className="chip text-[var(--text-muted)]">trigger</span>}
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
