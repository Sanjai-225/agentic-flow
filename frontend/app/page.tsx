"use client";

import React, { useState, useRef, useCallback } from "react";
import WorkflowToolbar from "@/components/WorkflowToolbar";
import PromptInput from "@/components/PromptInput";
import WorkflowCanvas from "@/components/WorkflowCanvas";
import { generateWorkflow } from "@/services/workflowApi";
import { WorkflowResponse } from "@/types/workflow";
import { Copy, Check, X } from "lucide-react";

export default function HomePage() {
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showJsonModal, setShowJsonModal] = useState(false);
  const [copied, setCopied] = useState(false);

  // Store canvas fit-view callback
  const fitViewRef = useRef<(() => void) | null>(null);

  const handleRegisterFitView = useCallback((trigger: () => void) => {
    fitViewRef.current = trigger;
  }, []);

  const handleFitView = useCallback(() => {
    if (fitViewRef.current) {
      fitViewRef.current();
    }
  }, []);

  const handleClear = useCallback(() => {
    setWorkflow(null);
    setError(null);
  }, []);

  const handleGenerate = async (prompt: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const data = await generateWorkflow(prompt);
      setWorkflow(data);
    } catch (err: any) {
      setError(err?.message || "Failed to generate workflow. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopyJson = () => {
    if (!workflow) return;
    navigator.clipboard.writeText(JSON.stringify(workflow, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      {/* Top Navigation Toolbar */}
      <WorkflowToolbar
        workflow={workflow}
        onFitView={handleFitView}
        onClear={handleClear}
        onViewJson={() => setShowJsonModal(true)}
      />

      {/* Prompt Input Section */}
      <PromptInput
        onGenerate={handleGenerate}
        isLoading={isLoading}
        error={error}
        onClearError={() => setError(null)}
      />

      {/* Main Interactive Workflow Canvas */}
      <main className="flex-1 relative w-full h-full min-h-0">
        <WorkflowCanvas
          workflow={workflow}
          onFitViewTrigger={handleRegisterFitView}
        />
      </main>

      {/* Workflow JSON Modal */}
      {showJsonModal && workflow && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="bg-slate-900 border border-slate-800 rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <h3 className="font-semibold text-sm text-slate-100">
                  Workflow JSON
                </h3>
                <span className="text-xs text-slate-500 font-mono">
                  {workflow.workflow_id}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyJson}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
                >
                  {copied ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-emerald-400">Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-slate-400" />
                      <span>Copy</span>
                    </>
                  )}
                </button>
                <button
                  onClick={() => setShowJsonModal(false)}
                  className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="p-4 overflow-auto flex-1 bg-slate-950 font-mono text-xs text-emerald-400 rounded-b-xl">
              <pre>{JSON.stringify(workflow, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
