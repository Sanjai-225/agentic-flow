'use client';

import { useState, useRef, useEffect, useCallback, KeyboardEvent } from 'react';
import { WorkflowResponse, ReviewIssue } from '@/types/workflow';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  workflow?: WorkflowResponse;
  timestamp: Date;
}

interface ChatPanelProps {
  onWorkflowGenerated: (workflow: WorkflowResponse) => void;
  onOpenCatalog?: () => void;
}

const EXAMPLE_PROMPTS = [
  'Customer support email automation with order lookup',
  'Invoice processing with approval and payment',
  'Research automation with web scraping and report generation',
  'CI/CD pipeline with testing, build, and deployment',
  'Social media content scheduling and analytics',
];

export default function ChatPanel({ onWorkflowGenerated, onOpenCatalog }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: 'Hi! I\'m your AI Workflow Designer. Describe any automation or business process, and I\'ll design a complete workflow for you.\n\nTry something like:\n• "Create an email support system that checks orders and responds automatically"\n• "Build an invoice approval pipeline with Slack notifications"',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingPhase, setLoadingPhase] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Phased loading status
  useEffect(() => {
    if (!isLoading) {
      setLoadingPhase(0);
      return;
    }
    const timer1 = setTimeout(() => setLoadingPhase(1), 3000);
    const timer2 = setTimeout(() => setLoadingPhase(2), 8000);
    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
    };
  }, [isLoading]);

  const handleSubmit = async (promptText?: string) => {
    const prompt = (promptText || input).trim();
    if (!prompt || isLoading) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: prompt,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    // Auto-resize textarea back
    if (textareaRef.current) {
      textareaRef.current.style.height = '44px';
    }

    try {
      const apiUrl =
        typeof process.env.NEXT_PUBLIC_API_URL === 'string'
          ? process.env.NEXT_PUBLIC_API_URL.replace(/\/+$/, '')
          : typeof window !== 'undefined'
          ? ''
          : 'http://localhost:8000';
      const res = await fetch(`${apiUrl}/api/workflows/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
      }

      const workflow: WorkflowResponse = await res.json();
      onWorkflowGenerated(workflow);

      const nodeList = workflow.nodes
        .map((n) => `• **${n.label}** (${n.type})${n.tool ? ` → ${n.tool.name}` : ''}`)
        .join('\n');

      // Build review status section
      let reviewSection = '';
      if (workflow.review_status) {
        if (workflow.review_status === 'passed') {
          reviewSection = '\n\n✅ **Verified** — Workflow passed semantic review';
        } else if (workflow.review_status === 'failed') {
          const issuesList = (workflow.review_issues || [])
            .map((issue: ReviewIssue) => `• [${issue.severity.toUpperCase()}] ${issue.description}`)
            .join('\n');
          reviewSection = `\n\n⚠️ **Review Issues Found**\n${issuesList}`;
        } else if (workflow.review_status === 'needs_clarification') {
          reviewSection = `\n\n❓ **Clarification Needed**\n${workflow.review_summary || ''}`;
        }
        if (workflow.correction_attempts && workflow.correction_attempts > 0) {
          reviewSection += `\n\n_Corrected ${workflow.correction_attempts} time(s)_`;
        }
      }

      const assistantMsg: ChatMessage = {
        id: `asst-${Date.now()}`,
        role: 'assistant',
        content: `✅ **${workflow.workflow_name}**\n\n${workflow.description}\n\n**Nodes (${workflow.nodes.length}):**\n${nodeList}\n\n**Connections:** ${workflow.edges.length} edges${reviewSection}\n\nThe workflow is now displayed on the canvas →`,
        workflow,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (error: any) {
      const errorMsg: ChatMessage = {
        id: `err-${Date.now()}`,
        role: 'error',
        content: `❌ Failed to generate workflow: ${error.message}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    // Auto-resize
    const el = e.target;
    el.style.height = '44px';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  };

  return (
    <div className="flex flex-col h-full bg-white border-r border-[var(--border)]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-[var(--accent)] flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-semibold text-[var(--text-primary)]">AI Workflow Designer</h1>
              <p className="text-xs text-[var(--text-muted)]">Describe your automation</p>
            </div>
          </div>
          {onOpenCatalog && (
            <button
              onClick={onOpenCatalog}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] hover:text-indigo-600 transition-colors flex items-center gap-1.5 font-medium shadow-2xs"
              title="Browse registered node types and tools"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
              Nodes
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[90%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-[var(--accent)] text-white rounded-br-md'
                  : msg.role === 'error'
                  ? 'bg-[var(--error-light)] text-[var(--error)] border border-red-200 rounded-bl-md'
                  : 'bg-[var(--surface-hover)] text-[var(--text-primary)] rounded-bl-md'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-[var(--surface-hover)] rounded-2xl rounded-bl-md px-4 py-3">
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-xs text-[var(--text-muted)]">
                  {loadingPhase === 0 && '🔄 Generating workflow...'}
                  {loadingPhase === 1 && '🔍 Reviewing workflow...'}
                  {loadingPhase === 2 && '✨ Finalizing...'}
                </span>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick prompts */}
      {messages.length <= 1 && (
        <div className="px-4 pb-2">
          <p className="text-xs text-[var(--text-muted)] mb-2">Quick start:</p>
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_PROMPTS.map((p, i) => (
              <button
                key={i}
                onClick={() => handleSubmit(p)}
                disabled={isLoading}
                className="text-xs px-3 py-1.5 rounded-full border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--accent-light)] hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors disabled:opacity-50"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="p-3 border-t border-[var(--border)]">
        <div className="flex items-end gap-2 bg-[var(--surface-hover)] rounded-xl px-3 py-2">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            placeholder="Describe your workflow..."
            disabled={isLoading}
            rows={1}
            className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] resize-none focus:outline-none disabled:opacity-50"
            style={{ height: '44px', maxHeight: '120px' }}
          />
          <button
            onClick={() => handleSubmit()}
            disabled={!input.trim() || isLoading}
            className="w-8 h-8 rounded-lg bg-[var(--accent)] text-white flex items-center justify-center hover:bg-[var(--accent-hover)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex-shrink-0"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19V5m0 0l-5 5m5-5l5 5" />
            </svg>
          </button>
        </div>
        <p className="text-[10px] text-[var(--text-muted)] mt-1.5 text-center">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}

