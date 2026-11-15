'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import ChatPanel from '@/components/ChatPanel';
import WorkflowNodeComponent from '@/components/CustomNode';
import { CredentialsDialog, RunDialog } from '@/components/editor/Dialogs';
import ExecutionPanel from '@/components/editor/ExecutionPanel';
import NodeConfigPanel from '@/components/editor/NodeConfigPanel';
import NodeLibrary from '@/components/editor/NodeLibrary';
import { CATEGORY_COLOR } from '@/lib/status';
import type { FlowNode } from '@/lib/workflowMapping';
import { useEditorStore } from '@/store/editorStore';
import type { WorkflowResponse } from '@/types/workflow';

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
  return (
    <div className="glass-strong absolute left-1/2 top-3 z-30 flex max-w-xl -translate-x-1/2 items-start gap-2 rounded-xl px-3 py-2 text-xs" style={{ color }} role="status">
      <span className="flex-1">{notice.text}</span>
      <button onClick={() => setNotice(null)} className="text-[var(--text-muted)]" aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}

export default function WorkflowEditor({ workflowId }: { workflowId: string | null }) {
  const s = useEditorStore();
  const [showDesigner, setShowDesigner] = useState(false);
  const [showRun, setShowRun] = useState(false);
  const [showCreds, setShowCreds] = useState(false);
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
  const sample = trigger?.data.node.config?.sample_payload ?? {};
  const running = s.execution && (s.execution.status === 'running' || s.execution.status === 'pending');

  return (
    <div className="flex h-screen w-screen flex-col gap-3 overflow-hidden p-3">
      {/* Toolbar */}
      <header className="glass flex items-center gap-2 rounded-2xl px-3 py-2">
        <Link href="/workflows" className="btn-ghost" title="All workflows">
          ←
        </Link>
        <input aria-label="Workflow name" className="w-72 bg-transparent text-sm font-semibold text-[var(--text-primary)] outline-none" value={s.name} onChange={(e) => s.setMeta({ name: e.target.value })} />
        <span className="text-[11px] text-[var(--text-muted)]">
          {s.workflowId ? `v${s.version}` : 'not saved'}
          {s.dirty ? ' · unsaved changes' : ''}
        </span>
        <div className="ml-auto flex items-center gap-2">
          {s.workflowId && (
            <label className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]" title="Webhook, form and schedule triggers only start runs while the workflow is active. Manual runs always work.">
              <input type="checkbox" aria-label="Workflow active" checked={s.active} onChange={(e) => s.setActive(e.target.checked)} />
              {s.active ? 'Active' : 'Inactive'}
            </label>
          )}
          <button className="btn-ghost" onClick={() => setShowDesigner((v) => !v)}>
            ✦ AI Designer
          </button>
          <button className="btn-ghost" onClick={() => setShowCreds(true)}>
            Credentials
          </button>
          <button className="btn-ghost" onClick={() => s.validate()} disabled={!!s.busy || !s.nodes.length}>
            {s.busy === 'validating' ? 'Validating…' : 'Validate'}
          </button>
          <button className="btn-ghost" onClick={() => s.save()} disabled={!!s.busy || !s.nodes.length}>
            {s.busy === 'saving' ? 'Saving…' : 'Save'}
          </button>
          {running ? (
            <button className="btn-danger" onClick={() => s.cancel()}>
              ■ Cancel run
            </button>
          ) : (
            <button className="btn-primary" onClick={() => setShowRun(true)} disabled={!!s.busy || !s.nodes.length}>
              {s.busy === 'starting' ? 'Starting…' : '▶ Run'}
            </button>
          )}
        </div>
      </header>

      {loadError && (
        <p className="rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--error-light)', color: 'var(--danger)' }}>
          {loadError}
        </p>
      )}

      <div className="flex min-h-0 flex-1 gap-3">
        {showDesigner ? (
          <aside className="glass w-[360px] flex-shrink-0 overflow-hidden rounded-2xl">
            <ChatPanel onWorkflowGenerated={onGenerated} onClose={() => setShowDesigner(false)} />
          </aside>
        ) : (
          <NodeLibrary />
        )}

        <main className="glass relative min-w-0 flex-1 overflow-hidden rounded-2xl">
          <Notice />
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
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="rgba(255,255,255,0.08)" />
            <Controls position="bottom-left" />
            <MiniMap
              position="bottom-right"
              pannable
              zoomable
              maskColor="rgba(0,0,0,0.4)"
              nodeColor={(n) => CATEGORY_COLOR[s.registryByOp[(n.data as any)?.node?.operation]?.category] || '#64748b'}
            />
          </ReactFlow>
          {s.nodes.length === 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-center text-xs text-[var(--text-muted)]">
              Add nodes from the library, or describe a workflow to the AI Designer.
            </div>
          )}
          <NodeConfigPanel />
        </main>
      </div>

      <ExecutionPanel />

      {showRun && (
        <RunDialog
          initial={sample}
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
