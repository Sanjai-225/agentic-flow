'use client';

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';

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
}

const EXAMPLE_PROMPTS = [
  'When run manually with an amount and a URL, fetch the URL over http only if the amount is above 100',
  'Customer support email automation with order lookup',
  'Invoice processing with approval and payment',
  'Research automation with web scraping and report generation',
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

export default function ChatPanel({ onWorkflowGenerated, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        "Describe an automation and I'll design it on the canvas. Generated workflows use the same schema and engine as manual ones — nodes that can't execute yet are flagged.",
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
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">AI Workflow Designer</h2>
          <p className="text-[11px] text-[var(--text-muted)]">Gemini designer · semantic review · schema validation</p>
        </div>
        {onClose && (
          <button className="btn-ghost px-2" onClick={onClose} aria-label="Close designer">
            ✕
          </button>
        )}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className="max-w-[94%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed"
              style={
                msg.role === 'user'
                  ? { background: 'var(--accent-strong)', color: 'white' }
                  : msg.role === 'error'
                    ? { background: 'var(--error-light)', color: 'var(--danger)' }
                    : { background: 'var(--surface-hover)', color: 'var(--text-secondary)' }
              }
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
                <div className="whitespace-pre-wrap break-words">{msg.content}</div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
            <span className="h-2 w-2 animate-pulse rounded-full bg-[var(--accent)]" />
            {['Generating workflow…', 'Reviewing workflow…', 'Finalizing…'][loadingPhase]}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length <= 1 && (
        <div className="px-4 pb-2">
          <p className="mb-1.5 text-[11px] text-[var(--text-muted)]">Try:</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_PROMPTS.map((p) => (
              <button key={p} onClick={() => handleSubmit(p)} disabled={isLoading} className="btn-ghost rounded-full text-left">
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-[var(--border)] p-3">
        <div className="flex items-end gap-2 rounded-xl px-3 py-2" style={{ background: 'var(--surface-sunken)' }}>
          <textarea
            aria-label="Describe your workflow"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Describe your workflow…"
            disabled={isLoading}
            rows={2}
            className="flex-1 resize-none bg-transparent text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
          />
          <button onClick={() => handleSubmit()} disabled={!input.trim() || isLoading} className="btn-primary h-8 w-8 p-0" aria-label="Generate">
            ↑
          </button>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-[var(--text-muted)]">Generating replaces the canvas content (unsaved changes are lost).</p>
      </div>
    </div>
  );
}
