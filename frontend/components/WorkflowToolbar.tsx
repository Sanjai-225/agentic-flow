"use client";

import React from "react";
import {
  Workflow,
  Maximize2,
  Trash2,
  Activity,
  Layers,
  FileCode,
} from "lucide-react";
import { WorkflowResponse } from "@/types/workflow";

interface WorkflowToolbarProps {
  workflow: WorkflowResponse | null;
  onFitView: () => void;
  onClear: () => void;
  onViewJson?: () => void;
}

export default function WorkflowToolbar({
  workflow,
  onFitView,
  onClear,
  onViewJson,
}: WorkflowToolbarProps) {
  const nodeCount = workflow?.nodes?.length || 0;
  const edgeCount = workflow?.edges?.length || 0;

  return (
    <header className="h-14 bg-slate-900 border-b border-slate-800 px-4 md:px-6 flex items-center justify-between z-20">
      {/* Left: App Logo & Current Workflow Title */}
      <div className="flex items-center gap-4 min-w-0">
        <div className="flex items-center gap-2.5 shrink-0">
          <div className="p-1.5 rounded-lg bg-indigo-600/20 border border-indigo-500/30 text-indigo-400">
            <Workflow className="w-5 h-5" />
          </div>
          <span className="font-bold text-sm tracking-tight text-white hidden sm:inline">
            AI Workflow Designer
          </span>
        </div>

        {workflow ? (
          <div className="flex items-center gap-2 pl-3 border-l border-slate-800 min-w-0">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-100 truncate max-w-[200px] md:max-w-xs">
                  {workflow.workflow_name || "Generated Workflow"}
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 border border-slate-700 text-slate-400 shrink-0">
                  {nodeCount} nodes • {edgeCount} edges
                </span>
              </div>
              {workflow.description && (
                <p className="text-[11px] text-slate-400 truncate max-w-sm hidden md:block">
                  {workflow.description}
                </p>
              )}
            </div>
          </div>
        ) : (
          <span className="text-xs text-slate-500 hidden md:inline pl-3 border-l border-slate-800">
            Design dynamic workflows using Gemini
          </span>
        )}
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2">
        {workflow && (
          <>
            {onViewJson && (
              <button
                onClick={onViewJson}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-800 border border-slate-700/80 rounded-lg transition-colors"
                title="View Workflow JSON"
              >
                <FileCode className="w-3.5 h-3.5 text-indigo-400" />
                <span className="hidden sm:inline">JSON</span>
              </button>
            )}

            <button
              onClick={onFitView}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-800 border border-slate-700/80 rounded-lg transition-colors"
              title="Fit workflow to canvas"
            >
              <Maximize2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Fit View</span>
            </button>

            <button
              onClick={onClear}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-rose-300 hover:text-rose-100 bg-rose-950/30 hover:bg-rose-950/60 border border-rose-800/40 rounded-lg transition-colors"
              title="Clear canvas"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Clear</span>
            </button>
          </>
        )}
      </div>
    </header>
  );
}
