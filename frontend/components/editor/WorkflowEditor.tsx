'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow } from '@xyflow/react';
import { AlertTriangle, ArrowLeft, CheckCircle2, CircleAlert, Info, KeyRound, Loader2, PanelLeftOpen, Play, Save, Sparkles, Square, X } from 'lucide-react';
import '@xyflow/react/dist/style.css';

import ChatPanel from '@/components/ChatPanel';
import WorkflowNodeComponent from '@/components/CustomNode';
import { CredentialsDialog, RunDialog } from '@/components/editor/Dialogs';
import ExecutionPanel from '@/components/editor/ExecutionPanel';
import NodeConfigPanel from '@/components/editor/NodeConfigPanel';
import NodeLibrary from '@/components/editor/NodeLibrary';
import { api } from '@/lib/api';
import { EXTERNAL_TRIGGERS, TRIGGER_LABEL, newExternalRuns, runPayloadHint, runPayloadTemplate } from '@/lib/runHelpers';
import { CATEGORY_COLOR } from '@/lib/status';
import type { FlowNode } from '@/lib/workflowMapping';
import { useEditorStore } from '@/store/editorStore';
import type { ExecutionSummary, WorkflowResponse } from '@/types/workflow';

const nodeTypes = { workflow: WorkflowNodeComponent };

function Notice() {
  const notice = useEditorStore((s) => s.notice);
  const setNotice = useEditorStore((s) => s.setNotice);
  useEffect(() => {
    if (!notice || notice.kind === 'error') return;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice, setNotice]);
  if (!notice) return null;
  const color = notice.kind === 'error' ? 'var(--danger)' : notice.kind === 'success' ? 'var(--success)' : 'var(--accent)';
  const Icon = notice.kind === 'error' ? CircleAlert : notice.kind === 'success' ? CheckCircle2 : Info;
  return (
    <div
      className="hud animate-fade-up absolute left-1/2 top-[76px] z-40 flex w-[min(36rem,calc(100%-1.5rem))] -translate-x-1/2 items-start gap-2 rounded-xl px-3 py-2.5 text-xs"
      style={{ color }}
      role="status"
    >
      <Icon size={15} className="mt-px flex-shrink-0" />
      <span className="flex-1">{notice.text}</span>
      <button onClick={() => setNotice(null)} className="text-[var(--text-muted)] transition-colors hover:text-[var(--text-primary)]" aria-label="Dismiss">
        <X size={14} />
      </button>
    </div>
  );
}

export default function WorkflowEditor({ workflowId }: { workflowId: string | null }) {
  const s = useEditorStore();
  const [showDesigner, setShowDesigner] = useState(false);
  const [showRun, setShowRun] = useState(false);
  const [showCreds, setShowCreds] = useState(false);
  const [dockOpen, setDockOpen] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const st = useEditorStore.getState();
    st.reset();
    st.loadRegistry().catch((e) => setLoadError(`Could not load the node registry: ${e.message}`));
    if (workflowId) {
      st.loadWorkflow(workflowId).catch((e) => setLoadError(`Could not load workflow: ${e.message}`));
    } else {
      setShowDesigner(true);
    }
    return () => useEditorStore.getState().pollController?.abort();
  }, [workflowId]);

  // Seed a Manual Trigger in new, empty workflows once the registry is available.
  useEffect(() => {
    const st = useEditorStore.getState();
    if (!workflowId && st.nodes.length === 0 && st.registryByOp['core.manual_trigger']) {
      st.addNode(st.registryByOp['core.manual_trigger'], { x: 0, y: 0 });
      useEditorStore.setState({ dirty: false, selectedNodeId: null });
    }
  }, [workflowId, s.registry.length]);

  const onGenerated = useCallback((wf: WorkflowResponse) => {
    useEditorStore.getState().loadDefinition(wf, { workflowId: useEditorStore.getState().workflowId, dirty: true });
    if (wf.execution_readiness) {
      useEditorStore.setState({
        validation: { valid: wf.execution_readiness.executable, issues: wf.execution_readiness.issues, order: [], trigger_node_id: null },
      });
    }
  }, []);

  const trigger = s.nodes.find((n) => s.registryByOp[n.data.node.operation || '']?.is_trigger);
  const triggerOp = trigger?.data.node.operation ?? null;
  const sample = runPayloadTemplate(triggerOp, trigger?.data.node.config);

  // Runs started outside the editor (public form, webhook, scheduler) appear automatically:
  // poll the history while the page is visible and open the newest new run.
  const watchedId = s.workflowId;
  const watchExternal = !!watchedId && !!triggerOp && EXTERNAL_TRIGGERS.has(triggerOp);
  useEffect(() => {
    if (!watchExternal || !watchedId) return;
    let known: Set<string> | null = null;
    let stopped = false;
    const tick = async () => {
      if (stopped || document.visibilityState !== 'visible') return;
      let rows: ExecutionSummary[];
      try {
        rows = await api.listExecutions(watchedId);
      } catch {
        return; // backend asleep / offline: try again next tick
      }
      if (stopped) return;
      if (known === null) {
        known = new Set(rows.map((r) => r.id));
        return;
      }
      const fresh = newExternalRuns(known, rows);
      rows.forEach((r) => known!.add(r.id));
      if (!fresh.length) return;
      const st = useEditorStore.getState();
      useEditorStore.setState({ executions: rows });
      const busy = st.execution && (st.execution.status === 'running' || st.execution.status === 'pending');
      if (!busy) {
        st.setNotice({ kind: 'info', text: `${TRIGGER_LABEL[fresh[0].trigger_type] ?? 'New run started'} — showing its execution.` });
        st.openExecution(fresh[0].id);
      }
    };
    tick();
    const timer = setInterval(tick, 5000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [watchExternal, watchedId]);
  const running = s.execution && (s.execution.status === 'running' || s.execution.status === 'pending');

  return (
    <div className="flex h-screen w-screen flex-col gap-2 overflow-hidden bg-[#07080C] p-2 sm:gap-3 sm:p-3">
      <div className="canvas-surface relative min-h-0 flex-1 overflow-hidden rounded-2xl border border-white/[0.06]">
        {/* Infinite canvas */}
        <main className="absolute inset-0">
          <ReactFlow<FlowNode>
            nodes={s.nodes}
            edges={s.edges}
            nodeTypes={nodeTypes}
            onNodesChange={s.onNodesChange}
            onEdgesChange={s.onEdgesChange}
            onConnect={s.onConnect}
            onNodeClick={(_, n) => s.selectNode(n.id)}
            onPaneClick={() => s.selectNode(null)}
            deleteKeyCode={['Backspace', 'Delete']}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            minZoom={0.2}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            colorMode="dark"
          >
            <Background variant={BackgroundVariant.Dots} gap={24} size={1.1} color="rgba(255,255,255,0.12)" />
            <Controls position="bottom-left" className={`transition-[left] duration-200 ${dockOpen ? 'md:!left-[332px]' : ''}`} />
            <MiniMap
              position="bottom-right"
              pannable
              zoomable
              className="!hidden md:!block"
              maskColor="rgba(7,8,12,0.6)"
              nodeColor={(n) => CATEGORY_COLOR[s.registryByOp[(n.data as any)?.node?.operation]?.category] || '#64748b'}
              nodeBorderRadius={6}
            />
          </ReactFlow>
          {s.nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6 text-center">
              <div className={`flex flex-col items-center gap-3 ${dockOpen ? 'md:pl-[320px]' : ''}`}>
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-indigo-400/25 bg-indigo-500/10 text-indigo-300 shadow-[0_0_40px_rgba(99,102,241,0.3)]">
                  <Sparkles size={20} />
                </span>
                <p className="max-w-xs text-xs text-[var(--text-muted)]">Add nodes from the library, or describe a workflow to the AI Designer.</p>
              </div>
            </div>
          )}
        </main>

        {/* Floating toolbar */}
        <header className="hud absolute left-2 right-2 top-2 z-30 flex items-center gap-2 rounded-xl px-2 py-2 sm:left-3 sm:right-3 sm:top-3 sm:px-3">
          <Link href="/workflows" className="btn-icon flex-shrink-0" title="All workflows" aria-label="All workflows">
            <ArrowLeft size={16} />
          </Link>
          <div className="h-5 w-px flex-shrink-0 bg-white/[0.08]" />
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <input
              aria-label="Workflow name"
              className="min-w-0 max-w-[18rem] flex-1 truncate rounded-md border border-transparent bg-transparent px-1.5 py-1 text-sm font-semibold tracking-tight text-[var(--text-primary)] outline-none transition-colors hover:border-white/[0.08] hover:bg-white/[0.03] focus:border-indigo-400/40 focus:bg-white/[0.04]"
              value={s.name}
              onChange={(e) => s.setMeta({ name: e.target.value })}
            />
            <span className="hidden flex-shrink-0 items-center gap-1.5 text-[11px] text-[var(--text-muted)] lg:flex">
              <span className="mono-badge">{s.workflowId ? `v${s.version}` : 'not saved'}</span>
              {s.dirty && (
                <span className="flex items-center gap-1 text-amber-300/90">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shadow-[0_0_6px_#fbbf24]" />
                  unsaved changes
                </span>
              )}
            </span>
          </div>
          <div className="flex flex-shrink-0 items-center gap-1.5 sm:gap-2">
            {s.workflowId && (
              <label
                className="flex cursor-pointer select-none items-center gap-2 rounded-lg px-1.5 py-1 text-[11px] font-medium text-[var(--text-secondary)]"
                title="Webhook, form and schedule triggers only start runs while the workflow is active. Manual runs always work."
              >
                <input type="checkbox" aria-label="Workflow active" className="peer sr-only" checked={s.active} onChange={(e) => s.setActive(e.target.checked)} />
                <span
                  className="relative h-[18px] w-8 flex-shrink-0 rounded-full border transition-all duration-200 peer-focus-visible:ring-2 peer-focus-visible:ring-indigo-400/50"
                  style={
                    s.active
                      ? { background: 'linear-gradient(135deg,#10b981,#06b6d4)', borderColor: 'rgba(110,231,183,0.5)', boxShadow: '0 0 14px rgba(16,185,129,0.45)' }
                      : { background: 'rgba(255,255,255,0.06)', borderColor: 'rgba(255,255,255,0.12)' }
                  }
                >
                  <span className={`absolute top-1/2 h-3 w-3 -translate-y-1/2 rounded-full bg-white shadow transition-all duration-200 ${s.active ? 'left-[15px]' : 'left-[2px] opacity-70'}`} />
                </span>
                <span className={`hidden sm:inline ${s.active ? 'text-emerald-300' : ''}`}>{s.active ? 'Active' : 'Inactive'}</span>
              </label>
            )}
            <div className="flex items-center rounded-lg border border-white/[0.08] bg-white/[0.03] p-0.5">
              <button
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all active:scale-[0.97] ${showDesigner && dockOpen ? 'bg-violet-500/15 text-violet-200 shadow-[inset_0_0_0_1px_rgba(167,139,250,0.35)]' : 'text-violet-300 hover:bg-violet-500/10'}`}
                onClick={() => {
                  setDockOpen(true);
                  setShowDesigner((v) => !(v && dockOpen));
                }}
                title="AI Designer"
              >
                <Sparkles size={14} />
                <span className="hidden bg-gradient-to-r from-violet-300 to-indigo-300 bg-clip-text text-transparent md:inline">AI Designer</span>
              </button>
              <button
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-all hover:bg-white/[0.06] hover:text-[var(--text-primary)] active:scale-[0.97]"
                onClick={() => setShowCreds(true)}
                title="Credentials"
              >
                <KeyRound size={14} />
                <span className="hidden md:inline">Credentials</span>
              </button>
              <button
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-all hover:bg-white/[0.06] hover:text-[var(--text-primary)] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40"
                onClick={() => s.validate()}
                disabled={!!s.busy || !s.nodes.length}
                title="Validate"
              >
                {s.busy === 'validating' ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                <span className="hidden md:inline">{s.busy === 'validating' ? 'Validating…' : 'Validate'}</span>
              </button>
              <button
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition-all hover:bg-white/[0.06] hover:text-[var(--text-primary)] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40"
                onClick={() => s.save()}
                disabled={!!s.busy || !s.nodes.length}
                title="Save"
              >
                {s.busy === 'saving' ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                <span className="hidden md:inline">{s.busy === 'saving' ? 'Saving…' : 'Save'}</span>
              </button>
            </div>
            {running ? (
              <button className="btn-danger px-3 py-[7px]" onClick={() => s.cancel()} title="Cancel run">
                <Square size={12} fill="currentColor" />
                <span className="hidden sm:inline">Cancel run</span>
              </button>
            ) : (
              <button className="btn-run px-3.5 py-[7px]" onClick={() => setShowRun(true)} disabled={!!s.busy || !s.nodes.length}>
                {s.busy === 'starting' ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} fill="currentColor" />}
                {s.busy === 'starting' ? 'Starting…' : 'Run'}
              </button>
            )}
          </div>
        </header>

        {loadError && (
          <p className="hud absolute left-1/2 top-[76px] z-30 flex w-[min(36rem,calc(100%-1.5rem))] -translate-x-1/2 items-center gap-2 rounded-xl px-3 py-2 text-xs text-rose-300">
            <AlertTriangle size={14} className="flex-shrink-0" />
            {loadError}
          </p>
        )}

        <Notice />

        {/* Floating left dock: node library / AI designer */}
        {dockOpen ? (
          <div className="hud animate-slide-in-left absolute bottom-2 left-2 top-[62px] z-20 flex w-80 max-w-[calc(100%-1rem)] flex-col overflow-hidden rounded-2xl sm:bottom-3 sm:left-3 sm:top-[72px]">
            {showDesigner ? (
              <ChatPanel onWorkflowGenerated={onGenerated} onClose={() => setShowDesigner(false)} onCollapse={() => setDockOpen(false)} />
            ) : (
              <NodeLibrary onCollapse={() => setDockOpen(false)} />
            )}
          </div>
        ) : (
          <button
            className="hud absolute left-2 top-[62px] z-20 flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-medium text-[var(--text-secondary)] transition-all hover:border-white/[0.18] hover:text-[var(--text-primary)] sm:left-3 sm:top-[72px]"
            onClick={() => setDockOpen(true)}
            title="Open panel"
          >
            <PanelLeftOpen size={15} />
            {showDesigner ? 'AI Designer' : 'Nodes'}
          </button>
        )}

        {/* Node configuration drawer (right) */}
        <NodeConfigPanel />
      </div>

      <ExecutionPanel />

      {showRun && (
        <RunDialog
          initial={sample}
          hint={runPayloadHint(triggerOp)}
          onClose={() => setShowRun(false)}
          onRun={(input) => {
            setShowRun(false);
            s.run(input);
          }}
        />
      )}
      {showCreds && <CredentialsDialog onClose={() => setShowCreds(false)} />}
    </div>
  );
}
