'use client';

import { useMemo, useState } from 'react';
import { Boxes, PanelLeftClose, Plus, Search } from 'lucide-react';

import { NodeIconTile, categoryIcon } from '@/lib/icons';
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

export default function NodeLibrary({ onCollapse }: { onCollapse?: () => void } = {}) {
  const registry = useEditorStore((s) => s.registry);
  const addNode = useEditorStore((s) => s.addNode);
  const [query, setQuery] = useState('');

  const grouped = useMemo(() => groupDefinitions(filterDefinitions(registry, query)), [registry, query]);

  return (
    <aside className="flex h-full w-full flex-col" aria-label="Node library">
      <div className="border-b border-[var(--border)] p-3">
        <div className="mb-2.5 flex items-center justify-between">
          <p className="flex items-center gap-2 text-[13px] font-semibold tracking-tight text-[var(--text-primary)]">
            <Boxes size={15} className="text-indigo-300" />
            Nodes
            <span className="mono-badge">{registry.length}</span>
          </p>
          {onCollapse && (
            <button className="btn-icon h-7 w-7" onClick={onCollapse} title="Collapse panel" aria-label="Collapse panel">
              <PanelLeftClose size={15} />
            </button>
          )}
        </div>
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input aria-label="Search nodes" className="field py-2 pl-8" placeholder="Search nodes…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto p-3">
        {grouped.length === 0 && <p className="text-[11px] text-[var(--text-muted)]">No nodes match “{query}”.</p>}
        {grouped.map(([category, defs]) => {
          const accent = categoryColor(category);
          const CatIcon = categoryIcon(category);
          return (
            <div key={category}>
              <p className="mb-2 flex items-center gap-1.5 px-0.5 text-[10px] font-semibold uppercase tracking-[0.1em]" style={{ color: accent }}>
                <CatIcon size={11} />
                {categoryLabel(category)}
                <span className="ml-1 h-px flex-1" style={{ background: `linear-gradient(90deg, ${accent}40, transparent)` }} />
              </p>
              <div className="space-y-1.5">
                {defs.map((d) => (
                  <button
                    key={d.operation_id}
                    onClick={() => addNode(d)}
                    title={d.description}
                    className="group flex w-full cursor-pointer items-center gap-2.5 rounded-lg border border-white/[0.05] bg-white/[0.02] p-2.5 text-left transition-all duration-150 hover:border-white/[0.15] hover:bg-white/[0.06] active:scale-[0.99]"
                    data-testid={`library-${d.operation_id}`}
                  >
                    <NodeIconTile operation={d.operation_id} category={d.category} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium text-[var(--text-primary)]">{d.label}</span>
                        {d.is_trigger && (
                          <span className="chip border border-amber-500/25 bg-amber-500/10 text-[9px] text-amber-300">trigger</span>
                        )}
                      </span>
                      <span className="block truncate font-mono text-[10px] text-[var(--text-muted)] transition-colors group-hover:text-[var(--text-secondary)]">{d.operation_id}</span>
                    </span>
                    <Plus size={14} className="flex-shrink-0 text-[var(--text-muted)] opacity-0 transition-opacity group-hover:opacity-100" />
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
