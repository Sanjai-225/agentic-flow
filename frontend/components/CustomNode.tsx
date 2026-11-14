'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { CustomNodeData } from '@/types/workflow';

const NODE_COLORS: Record<string, { bg: string; border: string; badge: string; badgeText: string }> = {
  // Input / Output & Triggers
  trigger:              { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  webhook:              { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  webhook_trigger:      { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  schedule:             { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  schedule_trigger:     { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  email_trigger:        { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  manual_trigger:       { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  input:                { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  output:               { bg: '#eef2ff', border: '#4f46e5', badge: '#e0e7ff', badgeText: '#3730a3' },
  webhook_output:       { bg: '#eef2ff', border: '#4f46e5', badge: '#e0e7ff', badgeText: '#3730a3' },
  email_output:         { bg: '#fdf2f8', border: '#ec4899', badge: '#fce7f3', badgeText: '#9d174d' },
  notification_output:  { bg: '#fdf2f8', border: '#ec4899', badge: '#fce7f3', badgeText: '#9d174d' },
  end:                  { bg: '#eef2ff', border: '#4f46e5', badge: '#e0e7ff', badgeText: '#3730a3' },

  // AI & Reasoning
  llm_agent:            { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  llm:                  { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  ai_processing:        { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  text_classifier:      { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  entity_extractor:     { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  summarizer:           { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },

  // Logic & Flow Control
  condition:            { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  decision:             { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  branch:               { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  switch:               { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  loop:                 { bg: '#fffbeb', border: '#d97706', badge: '#fef3c7', badgeText: '#92400e' },
  error_handler:        { bg: '#fff1f2', border: '#e11d48', badge: '#ffe4e6', badgeText: '#9f1239' },

  // Tools & Integrations
  database_query:       { bg: '#ecfdf5', border: '#10b981', badge: '#d1fae5', badgeText: '#065f46' },
  database_update:      { bg: '#ecfdf5', border: '#10b981', badge: '#d1fae5', badgeText: '#065f46' },
  database:             { bg: '#ecfdf5', border: '#10b981', badge: '#d1fae5', badgeText: '#065f46' },
  api_call:             { bg: '#eff6ff', border: '#3b82f6', badge: '#dbeafe', badgeText: '#1e40af' },
  api:                  { bg: '#eff6ff', border: '#3b82f6', badge: '#dbeafe', badgeText: '#1e40af' },
  tool_integration:     { bg: '#eff6ff', border: '#2563eb', badge: '#dbeafe', badgeText: '#1e40af' },
  file_operation:       { bg: '#f0fdfa', border: '#0d9488', badge: '#ccfbf1', badgeText: '#115e59' },
  notification:         { bg: '#fdf2f8', border: '#ec4899', badge: '#fce7f3', badgeText: '#9d174d' },
  email:                { bg: '#fdf2f8', border: '#ec4899', badge: '#fce7f3', badgeText: '#9d174d' },

  // Data Processing
  data_transform:       { bg: '#f0fdfa', border: '#14b8a6', badge: '#ccfbf1', badgeText: '#115e59' },
  transform:            { bg: '#f0fdfa', border: '#14b8a6', badge: '#ccfbf1', badgeText: '#115e59' },
  filter:               { bg: '#f0fdfa', border: '#14b8a6', badge: '#ccfbf1', badgeText: '#115e59' },
  code_execution:       { bg: '#f8fafc', border: '#64748b', badge: '#f1f5f9', badgeText: '#334155' },

  // Memory & Knowledge
  vector_search:        { bg: '#f0f9ff', border: '#0284c7', badge: '#e0f2fe', badgeText: '#0369a1' },
  knowledge_retrieval:  { bg: '#f0f9ff', border: '#0284c7', badge: '#e0f2fe', badgeText: '#0369a1' },

  // Human in the Loop
  human_approval:       { bg: '#fdf4ff', border: '#d946ef', badge: '#fae8ff', badgeText: '#86198f' },
  approval:             { bg: '#fdf4ff', border: '#d946ef', badge: '#fae8ff', badgeText: '#86198f' },
};

const DEFAULT_COLORS = { bg: '#f8fafc', border: '#94a3b8', badge: '#f1f5f9', badgeText: '#475569' };

function getColors(type: string) {
  const key = type.toLowerCase().replace(/[-\s]/g, '_');
  if (NODE_COLORS[key]) return NODE_COLORS[key];

  // Heuristic fallback matching by substring
  if (key.includes('trigger') || key.includes('webhook') || key.includes('schedule')) {
    return NODE_COLORS.trigger;
  }
  if (key.includes('llm') || key.includes('ai') || key.includes('agent') || key.includes('extract') || key.includes('classif')) {
    return NODE_COLORS.llm_agent;
  }
  if (key.includes('condition') || key.includes('decision') || key.includes('branch') || key.includes('switch')) {
    return NODE_COLORS.condition;
  }
  if (key.includes('database') || key.includes('sql') || key.includes('query')) {
    return NODE_COLORS.database_query;
  }
  if (key.includes('approval') || key.includes('human')) {
    return NODE_COLORS.human_approval;
  }
  if (key.includes('notify') || key.includes('email') || key.includes('alert') || key.includes('slack')) {
    return NODE_COLORS.notification_output;
  }
  if (key.includes('vector') || key.includes('memory') || key.includes('knowledge')) {
    return NODE_COLORS.vector_search;
  }
  if (key.includes('transform') || key.includes('format') || key.includes('filter')) {
    return NODE_COLORS.data_transform;
  }
  if (key.includes('output') || key.includes('end')) {
    return NODE_COLORS.output;
  }

  return DEFAULT_COLORS;
}

function CustomNode({ data, selected }: NodeProps) {
  const d = data as unknown as CustomNodeData;
  const colors = getColors(d.nodeType);
  const desc = d.description || '';
  const hasConfig = d.config && Object.keys(d.config).length > 0;

  return (
    <div
      className={`relative min-w-[240px] max-w-[300px] rounded-xl shadow-sm border-2 transition-all cursor-pointer hover:shadow-md ${
        selected ? 'ring-3 ring-indigo-500 ring-offset-2 shadow-lg' : ''
      }`}
      style={{ background: colors.bg, borderColor: colors.border }}
    >
      <Handle type="target" position={Position.Top} className="!w-3 !h-3 !border-2 !border-white" style={{ background: colors.border }} />

      <div className="px-4 py-3">
        {/* Type badge + tool */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <span
            className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full inline-flex items-center"
            style={{ background: colors.badge, color: colors.badgeText }}
          >
            {d.nodeType.replace(/_/g, ' ')}
          </span>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {hasConfig && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/70 border border-slate-200 text-slate-600 font-mono" title="Configured step">
                ⚙️
              </span>
            )}
            {d.tool && (
              <span className="text-[11px] font-medium text-slate-700 bg-white/80 px-1.5 py-0.5 rounded border border-slate-200/80 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                {d.tool.name}
              </span>
            )}
          </div>
        </div>

        {/* Label */}
        <h3 className="text-sm font-bold text-slate-900 leading-snug break-words mb-1">
          {d.label}
        </h3>

        {/* Description - clean, readable wrapping */}
        {desc && (
          <p className="text-xs text-slate-600 leading-relaxed break-words line-clamp-3">
            {desc}
          </p>
        )}

        {/* Start/End badge */}
        {(d.isStart || d.isEnd) && (
          <div className="mt-2.5 flex items-center gap-1.5 pt-2 border-t border-black/5">
            {d.isStart && (
              <span className="text-[9px] font-bold tracking-wide px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                START NODE
              </span>
            )}
            {d.isEnd && (
              <span className="text-[9px] font-bold tracking-wide px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800 border border-indigo-200">
                END NODE
              </span>
            )}
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!w-3 !h-3 !border-2 !border-white" style={{ background: colors.border }} />
    </div>
  );
}

export default memo(CustomNode);
