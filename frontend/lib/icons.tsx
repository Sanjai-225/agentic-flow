/* Presentation-only icon and colour helpers for node types and categories. */

import type { CSSProperties } from 'react';
import {
  Blocks,
  Bot,
  Box,
  Braces,
  BrainCircuit,
  CalendarClock,
  CalendarDays,
  Database,
  Filter,
  Flag,
  FormInput,
  GitBranch,
  GitMerge,
  Globe,
  Layers,
  MousePointerClick,
  PenLine,
  Repeat,
  Shuffle,
  Sparkles,
  Split,
  UserCheck,
  Webhook,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react';

import { categoryColor } from '@/lib/status';

const OPERATION_ICON: Record<string, LucideIcon> = {
  'core.manual_trigger': MousePointerClick,
  'core.webhook_trigger': Webhook,
  'core.form_trigger': FormInput,
  'core.schedule_trigger': CalendarClock,
  'core.end': Flag,
  'ai.agent': Bot,
  'ai.generate': Sparkles,
  'core.set': PenLine,
  'core.transform': Shuffle,
  'core.json_parse': Braces,
  'core.array': Layers,
  'core.datetime': CalendarDays,
  'core.filter': Filter,
  'core.if': GitBranch,
  'core.switch': Split,
  'core.loop': Repeat,
  'core.merge': GitMerge,
  'http.request': Globe,
};

const CATEGORY_ICON: Record<string, LucideIcon> = {
  input_output: Zap,
  ai_agent: BrainCircuit,
  data_processing: Database,
  logic: GitBranch,
  tools: Wrench,
  memory_knowledge: Blocks,
  human_in_the_loop: UserCheck,
};

export function nodeIcon(operation: string | null | undefined, category?: string): LucideIcon {
  return (operation && OPERATION_ICON[operation]) || (category && CATEGORY_ICON[category]) || Box;
}

export function categoryIcon(category: string): LucideIcon {
  return CATEGORY_ICON[category] || Box;
}

/** Frosted, colour-coded icon tile style for a category accent (hex). */
export function toneStyle(category: string | undefined): CSSProperties {
  const c = categoryColor(category);
  return { color: c, background: `${c}26`, border: `1px solid ${c}4d`, boxShadow: `0 0 14px ${c}26` };
}

export function NodeIconTile({ operation, category, size = 32 }: { operation?: string | null; category?: string; size?: number }) {
  const Icon = nodeIcon(operation, category);
  return (
    <span className="inline-flex flex-shrink-0 items-center justify-center rounded-lg" style={{ ...toneStyle(category), width: size, height: size }} aria-hidden>
      <Icon size={Math.round(size * 0.5)} strokeWidth={2} />
    </span>
  );
}
