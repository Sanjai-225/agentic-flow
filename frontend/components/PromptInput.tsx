"use client";

import React, { useState } from "react";
import { Sparkles, Loader2, AlertCircle, ArrowRight } from "lucide-react";

interface PromptInputProps {
  onGenerate: (prompt: string) => Promise<void>;
  isLoading: boolean;
  error: string | null;
  onClearError?: () => void;
}

const EXAMPLE_PROMPTS = [
  "When a new support email is received, analyze sentiment and urgency with Gemini. If high priority, notify on Slack and create a Jira issue; otherwise send an auto-reply.",
  "Fetch daily sales reports from Google Sheets, summarize key metrics and anomalies using AI, and email an executive brief to leadership.",
  "Monitor GitHub repository for new pull requests, run automated code review and security checks, and post summary comments.",
];

export default function PromptInput({
  onGenerate,
  isLoading,
  error,
  onClearError,
}: PromptInputProps) {
  const [prompt, setPrompt] = useState("");

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!prompt.trim() || isLoading) return;
    onGenerate(prompt.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSelectExample = (ex: string) => {
    setPrompt(ex);
    if (onClearError) onClearError();
  };

  return (
    <div className="w-full bg-slate-900/90 border-b border-slate-800 p-4 backdrop-blur-md">
      <div className="max-w-6xl mx-auto space-y-3">
        {/* Error notification */}
        {error && (
          <div className="flex items-start gap-3 p-3 text-xs bg-rose-950/50 border border-rose-800/60 rounded-lg text-rose-300 animate-in fade-in duration-200">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-semibold text-rose-200">Generation Failed</p>
              <p className="mt-0.5 break-words">{error}</p>
            </div>
            {onClearError && (
              <button
                onClick={onClearError}
                className="text-rose-400 hover:text-rose-200 text-xs px-2 py-0.5 rounded hover:bg-rose-900/40"
              >
                Dismiss
              </button>
            )}
          </div>
        )}

        {/* Input Form */}
        <form onSubmit={handleSubmit} className="relative">
          <div className="relative rounded-xl border border-slate-700/80 bg-slate-950/80 focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 transition-all shadow-inner">
            <textarea
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                if (error && onClearError) onClearError();
              }}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              rows={3}
              placeholder="Describe your workflow requirement in plain English (e.g. 'When a support ticket is created, classify sentiment with AI and route urgent issues to Slack...')"
              className="w-full bg-transparent px-4 pt-3 pb-12 text-sm text-slate-100 placeholder-slate-500 focus:outline-none resize-none disabled:opacity-60"
            />

            {/* Bottom bar inside textarea */}
            <div className="absolute bottom-2.5 left-4 right-3 flex items-center justify-between pointer-events-none">
              <span className="text-[11px] text-slate-500 hidden sm:inline">
                Press{" "}
                <kbd className="px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded border border-slate-700 text-[10px] font-mono">
                  Ctrl+Enter
                </kbd>{" "}
                to generate
              </span>

              <button
                type="submit"
                disabled={isLoading || !prompt.trim()}
                className="pointer-events-auto flex items-center gap-2 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 disabled:cursor-not-allowed text-white text-xs font-semibold rounded-lg shadow-md shadow-indigo-600/20 hover:shadow-indigo-500/30 transition-all ml-auto"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Architecting Workflow...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    <span>Generate Workflow</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </form>

        {/* Example prompts chips */}
        <div className="flex items-center gap-2 overflow-x-auto text-[11px] text-slate-400 pt-0.5 no-scrollbar">
          <span className="shrink-0 text-slate-500 font-medium">Examples:</span>
          {EXAMPLE_PROMPTS.map((ex, i) => (
            <button
              key={i}
              type="button"
              disabled={isLoading}
              onClick={() => handleSelectExample(ex)}
              className="shrink-0 max-w-xs md:max-w-md truncate px-2.5 py-1 rounded-md bg-slate-800/60 hover:bg-slate-800 text-slate-300 border border-slate-700/60 hover:border-slate-600 transition-colors text-left flex items-center gap-1.5 disabled:opacity-50"
            >
              <ArrowRight className="w-3 h-3 text-indigo-400 shrink-0" />
              <span className="truncate">{ex}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
