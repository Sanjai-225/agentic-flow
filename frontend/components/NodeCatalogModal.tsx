'use client';

import { useState, useEffect } from 'react';
import { NodeDefinition, RegistryCatalogResponse } from '@/types/workflow';
import { fetchNodeRegistry } from '@/services/workflowApi';

interface NodeCatalogModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const CATEGORY_LABELS: Record<string, string> = {
  all: 'All Nodes',
  input_output: 'Input & Output',
  ai_agent: 'AI & Agents',
  tools: 'Tools & Services',
  logic: 'Logic & Control',
  data_processing: 'Data Processing',
  memory_knowledge: 'Memory & RAG',
  human_in_the_loop: 'Human in Loop',
};

export default function NodeCatalogModal({ isOpen, onClose }: NodeCatalogModalProps) {
  const [catalog, setCatalog] = useState<RegistryCatalogResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  useEffect(() => {
    if (!isOpen) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchNodeRegistry()
      .then((data) => {
        if (isMounted) {
          setCatalog(data as RegistryCatalogResponse);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || 'Failed to load node catalog');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const categories = ['all', ...(catalog?.categories || [])];

  const filteredNodes = (catalog?.nodes || []).filter((node: NodeDefinition) => {
    const matchesCategory =
      selectedCategory === 'all' || node.category === selectedCategory;
    const query = searchQuery.toLowerCase().trim();
    const matchesSearch =
      !query ||
      node.label.toLowerCase().includes(query) ||
      node.node_type.toLowerCase().includes(query) ||
      node.description.toLowerCase().includes(query) ||
      (node.tags && node.tags.some((t) => t.toLowerCase().includes(query))) ||
      (node.compatible_tools &&
        node.compatible_tools.some((t) => t.name.toLowerCase().includes(query)));

    return matchesCategory && matchesSearch;
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl border border-[var(--border)] w-full max-w-4xl max-h-[88vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-[var(--border)] flex items-center justify-between bg-slate-50/50">
          <div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-indigo-600 inline-block" />
              <h2 className="text-lg font-semibold text-[var(--text-primary)]">Node Registry Catalog</h2>
              <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 font-medium border border-indigo-200">
                Phase 3
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Verified reusable node types and integrations recognized by the Workflow Architect LLM
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Search & Category Filter */}
        <div className="px-6 py-3 border-b border-[var(--border)] bg-white space-y-3">
          <div className="relative">
            <input
              type="text"
              placeholder="Search nodes by name, description, tags, or compatible tools (e.g. 'Gmail', 'SQL', 'condition')..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm bg-slate-50 border border-[var(--border)] rounded-xl focus:outline-none focus:border-indigo-500 focus:bg-white transition-colors"
            />
            <svg
              className="w-4 h-4 text-slate-400 absolute left-3 top-3"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </div>

          {/* Categories Horizontal Tabs */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none">
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`text-xs px-3 py-1.5 rounded-lg font-medium whitespace-nowrap transition-colors ${
                  selectedCategory === cat
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                }`}
              >
                {CATEGORY_LABELS[cat] || cat}
              </button>
            ))}
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 bg-slate-50/30">
          {loading && (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3" />
              <p className="text-sm">Loading registered nodes...</p>
            </div>
          )}

          {error && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
              <p className="font-semibold">Unable to load registry</p>
              <p className="text-xs mt-1">{error}</p>
            </div>
          )}

          {!loading && !error && filteredNodes.length === 0 && (
            <div className="text-center py-16 text-slate-400">
              <p className="text-sm font-medium">No nodes match your filter criteria.</p>
              <p className="text-xs mt-1">Try a different search keyword or category.</p>
            </div>
          )}

          {!loading && !error && filteredNodes.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredNodes.map((node) => (
                <div
                  key={node.node_type}
                  className="bg-white border border-[var(--border)] rounded-xl p-4 shadow-sm hover:shadow transition-shadow flex flex-col justify-between"
                >
                  <div>
                    {/* Header */}
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div>
                        <h4 className="text-sm font-semibold text-slate-900 leading-snug">{node.label}</h4>
                        <code className="text-[11px] font-mono text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                          {node.node_type}
                        </code>
                      </div>
                      <span className="text-[10px] uppercase tracking-wider font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-600 whitespace-nowrap">
                        {CATEGORY_LABELS[node.category] || node.category}
                      </span>
                    </div>

                    {/* Description */}
                    <p className="text-xs text-slate-600 leading-relaxed mb-3">{node.description}</p>

                    {/* Ports */}
                    <div className="space-y-1.5 text-[11px] pt-2 border-t border-slate-100 mb-3">
                      <div className="flex items-center gap-1.5 text-slate-500">
                        <span className="font-medium text-slate-700">Inputs:</span>
                        {node.inputs && node.inputs.length > 0 ? (
                          <span className="text-slate-600">
                            {node.inputs.map((p) => `${p.name} (${p.data_type})`).join(', ')}
                          </span>
                        ) : (
                          <span className="italic text-slate-400">None (Trigger/Entry)</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 text-slate-500">
                        <span className="font-medium text-slate-700">Outputs:</span>
                        {node.outputs && node.outputs.length > 0 ? (
                          <span className="text-slate-600">
                            {node.outputs.map((p) => `${p.name} (${p.data_type})`).join(', ')}
                          </span>
                        ) : (
                          <span className="italic text-slate-400">None (Terminal)</span>
                        )}
                      </div>
                    </div>

                    {/* Compatible Tools */}
                    {node.compatible_tools && node.compatible_tools.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 mt-2">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase">Tools:</span>
                        {node.compatible_tools.map((t, idx) => (
                          <span
                            key={idx}
                            className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200"
                          >
                            {t.name} ({t.operation})
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Tags */}
                  {node.tags && node.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-3 pt-2 border-t border-slate-100">
                      {node.tags.map((tag, idx) => (
                        <span key={idx} className="text-[9px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                          #{tag}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3 border-t border-[var(--border)] bg-slate-50/50 flex items-center justify-between text-xs text-slate-500">
          <span>
            {filteredNodes.length} of {catalog?.total_nodes || 0} registered nodes shown
          </span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-200 hover:bg-slate-300 text-slate-700 font-medium rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
