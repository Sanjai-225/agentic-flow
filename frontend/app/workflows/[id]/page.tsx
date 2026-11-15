'use client';

import dynamic from 'next/dynamic';

import RequireAuth from '@/components/RequireAuth';

const WorkflowEditor = dynamic(() => import('@/components/editor/WorkflowEditor'), { ssr: false });

export default function WorkflowEditorPage({ params }: { params: { id: string } }) {
  return (
    <RequireAuth>
      <WorkflowEditor workflowId={params.id === 'new' ? null : params.id} />
    </RequireAuth>
  );
}
