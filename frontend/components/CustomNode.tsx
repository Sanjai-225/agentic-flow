import React, { memo } from "react";
import { Handle, Position, NodeProps, Node } from "@xyflow/react";
import { CustomNodeData } from "@/types/workflow";
import {
  Zap,
  Bot,
  GitBranch,
  Wrench,
  Cpu,
  Send,
  Database,
  Box,
  Layers,
} from "lucide-react";

export type CustomNodeType = Node<CustomNodeData, "custom">;

// Color & icon mapping helper for dynamic node types
function getNodeTypeTheme(typeStr: string) {
  const t = (typeStr || "").toLowerCase().trim();

  if (t.includes("trigger") || t.includes("start") || t.includes("event") || t.includes("webhook")) {
    return {
      border: "border-emerald-500/50 hover:border-emerald-400",
      accent: "bg-emerald-500",
      badge: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
      glow: "shadow-emerald-500/10",
      icon: Zap,
    };
  }

  if (t.includes("llm") || t.includes("ai") || t.includes("agent") || t.includes("model") || t.includes("prompt") || t.includes("generate")) {
    return {
      border: "border-purple-500/50 hover:border-purple-400",
      accent: "bg-purple-500",
      badge: "bg-purple-500/15 text-purple-300 border-purple-500/30",
      glow: "shadow-purple-500/10",
      icon: Bot,
    };
  }

  if (t.includes("condition") || t.includes("decision") || t.includes("branch") || t.includes("router") || t.includes("switch") || t.includes("filter")) {
    return {
      border: "border-amber-500/50 hover:border-amber-400",
      accent: "bg-amber-500",
      badge: "bg-amber-500/15 text-amber-300 border-amber-500/30",
      glow: "shadow-amber-500/10",
      icon: GitBranch,
    };
  }

  if (t.includes("action") || t.includes("tool") || t.includes("api") || t.includes("integration") || t.includes("http")) {
    return {
      border: "border-cyan-500/50 hover:border-cyan-400",
      accent: "bg-cyan-500",
      badge: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
      glow: "shadow-cyan-500/10",
      icon: Wrench,
    };
  }

  if (t.includes("process") || t.includes("transform") || t.includes("compute") || t.includes("parse") || t.includes("format")) {
    return {
      border: "border-blue-500/50 hover:border-blue-400",
      accent: "bg-blue-500",
      badge: "bg-blue-500/15 text-blue-300 border-blue-500/30",
      glow: "shadow-blue-500/10",
      icon: Cpu,
    };
  }

  if (t.includes("output") || t.includes("end") || t.includes("notify") || t.includes("notification") || t.includes("email") || t.includes("response")) {
    return {
      border: "border-rose-500/50 hover:border-rose-400",
      accent: "bg-rose-500",
      badge: "bg-rose-500/15 text-rose-300 border-rose-500/30",
      glow: "shadow-rose-500/10",
      icon: Send,
    };
  }

  if (t.includes("db") || t.includes("database") || t.includes("store") || t.includes("memory") || t.includes("cache")) {
    return {
      border: "border-teal-500/50 hover:border-teal-400",
      accent: "bg-teal-500",
      badge: "bg-teal-500/15 text-teal-300 border-teal-500/30",
      glow: "shadow-teal-500/10",
      icon: Database,
    };
  }

  // Fallback for any unknown / custom node type
  return {
    border: "border-slate-700 hover:border-slate-500",
    accent: "bg-slate-500",
    badge: "bg-slate-800 text-slate-300 border-slate-700",
    glow: "shadow-slate-500/5",
    icon: Box,
  };
}

export const CustomNode = memo(({ data }: NodeProps<CustomNodeType>) => {
  const nodeData = (data || {}) as CustomNodeData;
  const {
    label = "Untitled Node",
    nodeType = "node",
    description = "",
    tool,
    isStart,
    isEnd,
    config,
  } = nodeData;

  const theme = getNodeTypeTheme(nodeType);
  const IconComponent = theme.icon;

  const configKeys = config ? Object.keys(config) : [];

  return (
    <div
      className={`group relative rounded-xl border bg-slate-900/95 p-4 shadow-xl transition-all duration-200 w-80 text-slate-100 ${theme.border} ${theme.glow}`}
    >
      {/* Input / Target Handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-3.5 !h-3.5 !bg-indigo-400 !border-2 !border-slate-950 !-top-2 hover:!scale-125 transition-transform"
      />

      {/* Top accent bar */}
      <div
        className={`absolute top-0 left-4 right-4 h-0.5 rounded-full ${theme.accent}`}
      />

      {/* Header: Icon + Type Badge + Start/End indicator */}
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <div className="p-1.5 rounded-md bg-slate-800/80 border border-slate-700/60 text-slate-200">
            <IconComponent className="w-4 h-4" />
          </div>
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-full border capitalize truncate max-w-[140px] ${theme.badge}`}
            title={nodeType}
          >
            {nodeType}
          </span>
        </div>

        {/* Start / End badge if applicable */}
        <div className="flex items-center gap-1 shrink-0">
          {isStart && (
            <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              Start
            </span>
          )}
          {isEnd && (
            <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30">
              End
            </span>
          )}
        </div>
      </div>

      {/* Node Label */}
      <h3 className="font-semibold text-sm text-slate-100 mb-1 leading-snug tracking-tight">
        {label}
      </h3>

      {/* Description */}
      {description && (
        <p
          className="text-xs text-slate-400 line-clamp-3 mb-2 leading-relaxed"
          title={description}
        >
          {description}
        </p>
      )}

      {/* Tool / Integration Badge */}
      {tool && (
        <div className="mt-2.5 pt-2 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-300">
          <div className="flex items-center gap-1.5 min-w-0">
            <Wrench className="w-3 h-3 text-cyan-400 shrink-0" />
            <span className="font-medium text-cyan-200 truncate">
              {tool.name}
            </span>
            {tool.operation && (
              <span className="text-slate-400 truncate">
                ({tool.operation})
              </span>
            )}
          </div>
          <span
            className={`text-[10px] px-1.5 py-0.2 rounded border font-mono shrink-0 ml-1 ${
              tool.status === "connected"
                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                : "bg-slate-800 text-slate-400 border-slate-700"
            }`}
          >
            {tool.status || "not_connected"}
          </span>
        </div>
      )}

      {/* Config parameters hint (if any) */}
      {configKeys.length > 0 && !tool && (
        <div className="mt-2 pt-2 border-t border-slate-800/80 flex items-center gap-1 text-[11px] text-slate-400">
          <Layers className="w-3 h-3 text-slate-500" />
          <span className="truncate">
            Config: {configKeys.slice(0, 3).join(", ")}
            {configKeys.length > 3 ? ` +${configKeys.length - 3}` : ""}
          </span>
        </div>
      )}

      {/* Output / Source Handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-3.5 !h-3.5 !bg-indigo-400 !border-2 !border-slate-950 !-bottom-2 hover:!scale-125 transition-transform"
      />
    </div>
  );
});

CustomNode.displayName = "CustomNode";
export default CustomNode;
