/* Node ports for a concrete config. Mirrors backend NodeDefinition.ports_for exactly, so the editor shows the
 * same handles the planner validates (Switch: one output per case + "default"; Merge: input_1..input_N). */

import type { NodeDefinition } from '@/types/workflow';

export function portsFor(def: NodeDefinition | undefined, config: Record<string, any> | undefined): { in: string[]; out: string[] } {
  if (!def) return { in: ['main'], out: ['main'] };
  let portsIn = [...def.ports_in];
  let portsOut = [...def.ports_out];
  const spec = def.dynamic_ports;
  if (!spec) return { in: portsIn, out: portsOut };
  const value = config?.[spec.config_key];
  const ports: string[] = [];
  if (spec.source === 'list' && Array.isArray(value)) {
    for (const item of value.slice(0, spec.max_count)) {
      const key = spec.key_field && item && typeof item === 'object' ? item[spec.key_field] : undefined;
      if (typeof key === 'string' && key && !ports.includes(key)) ports.push(key);
    }
  } else if (spec.source === 'count') {
    let count = Number.parseInt(String(value ?? spec.min_count), 10);
    if (!Number.isFinite(count)) count = spec.min_count;
    count = Math.max(spec.min_count, Math.min(spec.max_count, count));
    for (let i = 1; i <= count; i += 1) ports.push(`${spec.prefix || 'input_'}${i}`);
  }
  for (const p of spec.fixed || []) if (!ports.includes(p)) ports.push(p);
  if (spec.direction === 'in') portsIn = ports;
  else portsOut = ports;
  return { in: portsIn, out: portsOut };
}

export const PORT_COLOR: Record<string, string> = {
  true: 'var(--success)',
  false: 'var(--danger)',
  default: 'var(--text-muted)',
  done: 'var(--accent)',
  item: 'var(--warning)',
};
