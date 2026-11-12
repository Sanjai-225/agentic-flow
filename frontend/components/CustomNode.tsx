'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { CustomNodeData } from '@/types/workflow';

const NODE_COLORS: Record<string, { bg: string; border: string; badge: string; badgeText: string }> = {
  trigger:        { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  webhook:        { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  schedule:       { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  input:          { bg: '#fefce8', border: '#eab308', badge: '#fef08a', badgeText: '#854d0e' },
  llm_agent:      { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  llm:            { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  ai_processing:  { bg: '#f5f3ff', border: '#8b5cf6', badge: '#ede9fe', badgeText: '#5b21b6' },
  condition:      { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  decision:       { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  branch:         { bg: '#fff7ed', border: '#f97316', badge: '#ffedd5', badgeText: '#9a3412' },
  database_query: { bg: '#ecfdf5', border: '#10b981', badge: '#d1fae5', badgeText: '#065f46' },
  database:       { bg: '#ecfdf5', border: '#10b981', badge: '#d1fae5', badgeText: '#065f46' },
  api_call:       { bg: '#eff6ff', border: '#3b82f6', badge: '#dbeafe', badgeText: '#1e40af' },
  api:            { bg: '#eff6ff', border: '#3b82f6', badge: '#dbeafe', badgeText: '#1e40af' },
  notification:   { bg: '#fdf2f8', border: '#ec4899', badge: '#fce7f3', badgeText: '#9d174d' },
  email:          { bg: '#fdf2f8', border: '#ec4899', badge: '#fce7f3', badgeText: '#9d174d' },
  approval:       { bg: '#fdf4ff', border: '#d946ef', badge: '#fae8ff', badgeText: '#86198f' },
  transform:      { bg: '#f0fdfa', border: '#14b8a6', badge: '#ccfbf1', badgeText: '#115e59' },
  output:         { bg: '#eef2ff', border: '#4f46e5', badge: '#e0e7ff', badgeText: '#3730a3' },
  end:            { bg: '#eef2ff', border: '#4f46e5', badge: '#e0e7ff', badgeText: '#3730a3' },
};

const DEFAULT_COLORS = { bg: '#f8fafc', border: '#94a3b8', badge: '#f1f5f9', badgeText: '#475569' };

function getColors(type: string) {
  const key = type.toLowerCase().replace(/[-\s]/g, '_');
  return NODE_COLORS[key] || DEFAULT_COLORS;
}

function CustomNode({ data }: NodeProps) {
  const d = data as unknown as CustomNodeData;
  const colors = getColors(d.nodeType);
  const desc = d.description?.length > 80 ? d.description.slice(0, 80) + '…' : d.description;

  return (
    <div
      className="relative min-w-[220px] max-w-[280px] rounded-xl shadow-sm border-2 transition-shadow hover:shadow-md"
      style={{ background: colors.bg, borderColor: colors.border }}
    >
      <Handle type="target" position={Position.Top} className="!w-3 !h-3 !border-2 !border-white" style={{ background: colors.border }} />

      <div className="px-3.5 py-3">
        {/* Type badge + tool */}
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <span
            className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
            style={{ background: colors.badge, color: colors.badgeText }}
          >
            {d.nodeType}
          </span>
          {d.tool && (
            <span className="text-[10px] text-[var(--text-muted)] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
              {d.tool.name}
            </span>
          )}
        </div>

        {/* Label */}
        <h3 className="text-sm font-semibold text-[var(--text-primary)] leading-tight mb-1">{d.label}</h3>

        {/* Description */}
        {desc && <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{desc}</p>}

        {/* Start/End badge */}
        {(d.isStart || d.isEnd) && (
          <div className="mt-2 flex gap-1">
            {d.isStart && (
              <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-green-100 text-green-700">START</span>
            )}
            {d.isEnd && (
              <span className="text-[9px] font-medium px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700">END</span>
            )}
          </div>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!w-3 !h-3 !border-2 !border-white" style={{ background: colors.border }} />
    </div>
  );
}

export default memo(CustomNode);
