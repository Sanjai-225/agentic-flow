'use client';

import { useState } from 'react';
import dynamic from 'next/dynamic';
import ChatPanel from '@/components/ChatPanel';
import { WorkflowResponse } from '@/types/workflow';

const WorkflowCanvas = dynamic(() => import('@/components/WorkflowCanvas'), { ssr: false });

export default function Home() {
  const [workflow, setWorkflow] = useState<WorkflowResponse | null>(null);

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-[var(--background)]">
      {/* Left: Chat Panel */}
      <div className="w-[380px] min-w-[320px] max-w-[440px] flex-shrink-0 h-full">
        <ChatPanel onWorkflowGenerated={setWorkflow} />
      </div>

      {/* Right: Canvas */}
      <div className="flex-1 h-full relative">
        <WorkflowCanvas workflow={workflow} />
      </div>
    </div>
  );
}
