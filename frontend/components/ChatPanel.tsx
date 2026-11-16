'use client';

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { AlertTriangle, ArrowUp, ArrowUpRight, Loader2, PanelLeftClose, Sparkles, X } from 'lucide-react';

import { api } from '@/lib/api';
import type { ReviewIssue, WorkflowResponse } from '@/types/workflow';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  workflow?: WorkflowResponse;
}

interface ChatPanelProps {
  onWorkflowGenerated: (workflow: WorkflowResponse) => void;
  onClose?: () => void;
  /** Collapse the dock that hosts the panel (presentation only). */
  onCollapse?: () => void;
}

/**
 * Starter scenarios. Each prompt only uses executable nodes and is specific enough for the designer to
 * produce a runnable workflow. "AI" scenarios need a provider credential selected in their AI nodes.
 */
export const EXAMPLE_PROMPTS: { title: string; description: string; prompt: string }[] = [
  {
    title: 'Order priority router',
    description: 'Webhook receives an order; IF amount ≥ 1000 marks it high priority, otherwise normal.',
    prompt:
      'Webhook trigger receives an order JSON with order_id, customer and amount. If amount is at least 1000, set priority to "high", otherwise set priority to "normal". End with order_id, customer and priority.',
  },
  {
    title: 'AI support-ticket triage',
    description: 'Webhook ticket → AI classifies category & urgency (JSON) → Switch routes billing / technical / general. Needs an AI credential.',
    prompt:
      'Webhook trigger receives a support ticket with customer_email, subject and message. Use AI Generate with Gemini model gemini-3.5-flash to return JSON with category (billing, technical or general), urgency (low, medium or high) and a one-line summary. Then use a Switch on the category with cases billing, technical and general; each case uses a Set node that adds team set to the category name. End with the team, urgency, summary and customer_email.',
  },
  {
    title: 'Contact form auto-reply',
    description: 'Public form (name, email, message) → AI writes a friendly reply. Needs an AI credential.',
    prompt:
      'Form Submission Trigger titled "Contact us" with required fields name (text), email (email) and message (textarea). Use AI Generate with Gemini model gemini-3.5-flash to write a short friendly reply to the message, addressed to the name. End with the email and the reply.',
  },
  {
    title: 'Invoice calculator agent',
    description: 'AI Agent uses the calculator and data_aggregate tools to compute subtotal, tax and total. Needs an AI credential.',
    prompt:
      'Manual trigger with sample payload {"items": [{"price": 40, "qty": 2}, {"price": 25, "qty": 3}], "tax_rate": 0.18}. An AI Agent with Gemini model gemini-3.5-flash and the calculator and data_aggregate tools computes subtotal, tax and total from the trigger items and tax_rate, returning JSON with subtotal, tax and total. End with the agent result.',
  },
  {
    title: 'Batch welcome messages',
    description: 'Loop over a list of names, build a message for each, then collect the results.',
    prompt:
      'Manual trigger with sample payload {"names": ["Asha", "Ravi", "Meena"]}. Loop Over Items with items {{trigger.names}}. Connect the loop\'s "item" output to a Set node that builds message = "Welcome {{item}}!"; that Set node is the loop body and has no outgoing connections. Connect the loop\'s "done" output to an End node whose output is the loop results {{nodes.loop_1.output.results}}.',
  },
  {
    title: 'Scheduled GitHub digest',
    description: 'Every weekday 9:00 (IST), fetch open issues from a public GitHub repo and summarise them with AI. Needs an AI credential.',
    prompt:
      'Schedule Trigger on weekdays at 09:00 in timezone Asia/Kolkata. HTTP Request GET https://api.github.com/repos/vercel/next.js/issues?per_page=10. Use AI Generate with Gemini model gemini-3.5-flash to write a short digest of the issue titles from the response body. End with the digest.',
  },
];

/** Render inline **bold**, _italic_ and `code`. */
export function renderFormattedInline(text: string) {
  const parts = text.split(/(\*\*.*?\*\*|_.*?_|`.*?`)/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index} className="font-semibold text-[var(--text-primary)]">{part.slice(2, -2)}</strong>;
    if (part.startsWith('_') && part.endsWith('_') && part.length > 2) return <em key={index} className="italic text-[var(--text-secondary)]">{part.slice(1, -1)}</em>;
    if (part.startsWith('`') && part.endsWith('`'))
      return (
        <code key={index} className="rounded px-1 py-0.5 font-mono text-xs text-[var(--accent-hover)]" style={{ background: 'var(--surface-hover)' }}>
          {part.slice(1, -1)}
        </code>
      );
    return part;
  });
}

export function summarizeWorkflow(workflow: WorkflowResponse): string {
  const nodeList = workflow.nodes.map((n) => `• **${n.label}** \`${n.operation || n.type}\`${n.tool ? ` → ${n.tool.name}` : ''}`).join('\n');
  let review = '';
  if (workflow.review_status === 'passed') review = '\n\n**Semantic review:** passed';
  else if (workflow.review_status === 'failed')
    review = `\n\n**Semantic review issues**\n${(workflow.review_issues || []).map((i: ReviewIssue) => `• [${i.severity.toUpperCase()}] ${i.description}`).join('\n')}`;
  else if (workflow.review_status === 'needs_clarification') review = `\n\n**Clarification needed**\n${workflow.review_summary || ''}`;

  const readiness = workflow.execution_readiness;
  let exec = '';
  if (readiness) {
    if (readiness.executable) exec = '\n\n**Execution readiness:** every node is executable. Save and click Run.';
    else {
      const unsupported = readiness.issues.filter((i) => i.severity === 'error').slice(0, 6);
      exec = `\n\n**Execution readiness:** not runnable yet\n${unsupported.map((i) => `• ${i.message}`).join('\n')}`;
    }
  }
  return `**${workflow.workflow_name}**\n\n${workflow.description}\n\n**Nodes (${workflow.nodes.length}):**\n${nodeList}${review}${exec}`;
}

export default function ChatPanel({ onWorkflowGenerated, onClose, onCollapse }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        "Describe an automation and I'll design it on the canvas. Every generated workflow is checked against the real engine before you can run it.",
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingPhase, setLoadingPhase] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);

  // Effects must return nothing or a cleanup function. Newer browsers return a Promise from
  // scrollIntoView(), so never return its result from an effect.
  const scrollToBottom = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);
  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);
  useEffect(() => {
    if (!isLoading) {
      setLoadingPhase(0);
      return undefined;
    }
    const t1 = setTimeout(() => setLoadingPhase(1), 3000);
    const t2 = setTimeout(() => setLoadingPhase(2), 8000);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [isLoading]);

  const handleSubmit = async (promptText?: string) => {
    const prompt = (promptText || input).trim();
    if (!prompt || isLoading) return;
    setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: 'user', content: prompt }]);
    setInput('');
    setIsLoading(true);
    try {
      const workflow = await api.generate(prompt);
      onWorkflowGenerated(workflow);
      setMessages((prev) => [...prev, { id: `a-${Date.now()}`, role: 'assistant', content: summarizeWorkflow(workflow), workflow }]);
    } catch (error: any) {
      setMessages((prev) => [...prev, { id: `e-${Date.now()}`, role: 'error', content: `Failed to generate workflow: ${error.message}` }]);
    } finally {
      setIsLoading(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="relative flex h-full flex-col">
      {/* Ambient aura */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-violet-600/20 via-indigo-600/[0.07] to-transparent" />
      <div className="pointer-events-none absolute -top-16 left-1/2 h-32 w-48 -translate-x-1/2 rounded-full bg-violet-500/25 blur-3xl" />
      <div className="relative flex items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-violet-400/30 bg-gradient-to-br from-violet-500/30 to-indigo-500/20 text-violet-200 shadow-[0_0_18px_rgba(139,92,246,0.4)]">
            <Sparkles size={15} />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[13px] font-semibold tracking-tight text-[var(--text-primary)]">AI Workflow Designer</h2>
            <p className="truncate text-[10.5px] text-[var(--text-muted)]">Gemini designer · semantic review · schema validation</p>
          </div>
        </div>
        <div className="flex flex-shrink-0 gap-0.5">
          {onCollapse && (
            <button className="btn-icon h-7 w-7" onClick={onCollapse} title="Collapse panel" aria-label="Collapse panel">
              <PanelLeftClose size={15} />
            </button>
          )}
          {onClose && (
            <button className="btn-icon h-7 w-7" onClick={onClose} aria-label="Close designer" title="Close designer">
              <X size={15} />
            </button>
          )}
        </div>
      </div>

      <div className="relative flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`animate-fade-up max-w-[94%] rounded-2xl px-3.5 py-2.5 text-[12.5px] leading-relaxed ${
                msg.role === 'user'
                  ? 'rounded-br-md border border-indigo-300/25 bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-[0_6px_20px_-6px_rgba(99,102,241,0.6)]'
                  : msg.role === 'error'
                    ? 'border border-rose-500/20 bg-rose-500/10 text-rose-300'
                    : 'rounded-bl-md border border-white/[0.06] bg-white/[0.04] text-[var(--text-secondary)]'
              }`}
            >
              {msg.role === 'assistant' ? (
                <div className="space-y-2 break-words">
                  {msg.content.split('\n\n').map((para, p) => (
                    <div key={p} className="space-y-0.5">
                      {para.split('\n').map((line, l) =>
                        line.startsWith('• ') ? (
                          <div key={l} className="flex gap-2 pl-1">
                            <span className="text-[var(--accent)]">•</span>
                            <span className="flex-1">{renderFormattedInline(line.slice(2))}</span>
                          </div>
                        ) : (
                          <p key={l}>{renderFormattedInline(line)}</p>
                        ),
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex gap-2 whitespace-pre-wrap break-words">
                  {msg.role === 'error' && <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />}
                  <span className="min-w-0 flex-1">{msg.content}</span>
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex items-center gap-2 rounded-xl border border-violet-400/15 bg-violet-500/[0.07] px-3 py-2 text-[11px] text-violet-200">
            <Loader2 size={13} className="animate-spin" />
            {['Generating workflow…', 'Reviewing workflow…', 'Finalizing…'][loadingPhase]}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length <= 1 && (
        <div className="relative px-4 pb-2">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--text-muted)]">Try a ready-to-run workflow:</p>
          <div className="max-h-64 space-y-1.5 overflow-y-auto pr-0.5">
            {EXAMPLE_PROMPTS.map((p) => (
              <button
                key={p.title}
                onClick={() => handleSubmit(p.prompt)}
                disabled={isLoading}
                title={p.prompt}
                className="group block w-full rounded-xl border border-white/[0.06] bg-white/[0.025] px-3 py-2 text-left transition-all duration-150 hover:border-violet-400/30 hover:bg-violet-500/[0.08] hover:shadow-[0_0_20px_-6px_rgba(139,92,246,0.5)] disabled:opacity-50"
              >
                <span className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-primary)]">
                  <Sparkles size={11} className="flex-shrink-0 text-violet-300/70 transition-colors group-hover:text-violet-300" />
                  <span className="flex-1 truncate">{p.title}</span>
                  <ArrowUpRight size={12} className="flex-shrink-0 text-[var(--text-muted)] opacity-0 transition-all group-hover:text-violet-300 group-hover:opacity-100" />
                </span>
                <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-[var(--text-muted)]">{p.description}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="relative border-t border-[var(--border)] p-3">
        <div className="relative rounded-xl border border-white/[0.08] bg-white/[0.035] px-3 pb-2 pt-2.5 transition-all duration-200 focus-within:border-violet-400/45 focus-within:bg-white/[0.05] focus-within:shadow-[0_0_0_3px_rgba(139,92,246,0.12),0_0_30px_-8px_rgba(139,92,246,0.5)]">
          <textarea
            aria-label="Describe your workflow"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Describe your workflow…"
            disabled={isLoading}
            rows={3}
            className="block w-full resize-none bg-transparent text-[13px] leading-relaxed text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
          />
          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="hidden items-center gap-1 text-[10px] text-[var(--text-muted)] sm:flex">
              <span className="kbd">Enter</span> to generate · <span className="kbd">Shift+Enter</span> newline
            </span>
            <button
              onClick={() => handleSubmit()}
              disabled={!input.trim() || isLoading}
              className="btn-primary ml-auto h-7 gap-1 rounded-lg px-2.5 text-[11px]"
              aria-label="Generate"
              title="Generate"
            >
              {isLoading ? <Loader2 size={13} className="animate-spin" /> : <ArrowUp size={13} strokeWidth={2.5} />}
              <span>Generate</span>
            </button>
          </div>
        </div>
        <p className="mt-2 text-center text-[10px] text-[var(--text-muted)]">Generating replaces the canvas content (unsaved changes are lost).</p>
      </div>
    </div>
  );
}
