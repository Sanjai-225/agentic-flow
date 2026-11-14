'use client';

import { useState, useEffect } from 'react';
import { type Node } from '@xyflow/react';
import { CustomNodeData, NodeDefinition } from '@/types/workflow';

interface NodeConfigPanelProps {
  node: Node | null;
  onClose: () => void;
  onUpdateConfig?: (nodeId: string, newConfig: Record<string, any>, newLabel?: string) => void;
}

// Field descriptions dictionary for common workflow configurations
const FIELD_EXPLANATIONS: Record<string, string> = {
  inbox: 'Email address or inbox folder monitored by this trigger node.',
  mailbox: 'Target email account mailbox (e.g. ap@company.com).',
  filter: 'Search query or predicate to filter incoming messages (e.g. has:attachment .pdf).',
  polling_interval_sec: 'Frequency in seconds between successive inbox or API checks.',
  cron: 'Standard 5-part cron expression specifying the schedule cadence.',
  timezone: 'Timezone applied when calculating trigger occurrences (e.g. UTC, America/New_York).',
  method: 'HTTP request method (GET, POST, PUT, DELETE, PATCH).',
  url: 'Target HTTP REST API endpoint destination.',
  path: 'Webhook URL route path where inbound events are received.',
  query: 'SQL or database query string executed against the database.',
  table: 'Database table or collection name targeted for query or update.',
  key: 'Primary or lookup key identifier used in database lookups.',
  threshold: 'Numeric threshold value evaluated in the decision expression.',
  currency: 'Monetary currency code applied to financial amounts (e.g. USD, EUR).',
  condition: 'Logical or boolean expression evaluated to determine branch routing.',
  expression: 'Conditional rule expression (e.g. amount > 5000).',
  model: 'AI model utilized for reasoning and generation (e.g. gemini-3.8-flash).',
  temperature: 'Sampling temperature controlling AI creativity (0.0 = deterministic, 1.0 = creative).',
  prompt: 'Custom prompt template or instruction given to the AI model.',
  system_instruction: 'Persona or operational guidelines guiding the AI agent behavior.',
  channel: 'Communication channel or room where notifications or approval cards are sent.',
  mention: 'User or group handle tagged for immediate alerting (e.g. @oncall, @finance-lead).',
  timeout_hours: 'Maximum duration in hours before an approval request expires or auto-escalates.',
  approver_role: 'Role or department authorized to grant approval (e.g. Finance Manager, Team Lead).',
  payment_method: 'Disbursement method used for payout (e.g. ACH, Wire, Card).',
  terms: 'Payment settlement terms (e.g. Net-30, Due Upon Receipt).',
  template: 'Email or document template name used for composition.',
  categories: 'Predefined classification labels assigned during text categorization.',
  extract_entities: 'List of target fields or entity names to parse out from unstructured text.',
};

export default function NodeConfigPanel({ node, onClose, onUpdateConfig }: NodeConfigPanelProps) {
  const [activeTab, setActiveTab] = useState<'config' | 'ports' | 'tool' | 'raw'>('config');
  const [configValues, setConfigValues] = useState<Record<string, any>>({});
  const [nodeLabel, setNodeLabel] = useState<string>('');
  const [registryNode, setRegistryNode] = useState<NodeDefinition | null>(null);
  const [isSaved, setIsSaved] = useState<boolean>(false);

  const data = node ? (node.data as unknown as CustomNodeData) : null;

  // Sync state whenever selected node changes
  useEffect(() => {
    if (data) {
      setConfigValues(data.config ? { ...data.config } : {});
      setNodeLabel(data.label || '');
      setIsSaved(false);

      // Fetch node registry specs for this node type
      const nodeType = data.nodeType?.toLowerCase().replace(/[-\s]/g, '_');
      fetch(`/api/registry/nodes/${encodeURIComponent(nodeType)}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((def) => setRegistryNode(def))
        .catch(() => setRegistryNode(null));
    }
  }, [node, data]);

  if (!node || !data) return null;

  const handleConfigChange = (key: string, value: any) => {
    setConfigValues((prev) => ({ ...prev, [key]: value }));
    setIsSaved(false);
  };

  const handleSave = () => {
    if (onUpdateConfig) {
      onUpdateConfig(node.id, configValues, nodeLabel);
      setIsSaved(true);
      setTimeout(() => setIsSaved(false), 2000);
    }
  };

  const configKeys = Object.keys(configValues);

  return (
    <div className="absolute top-3 right-3 bottom-3 w-[420px] max-w-[90vw] bg-white rounded-2xl shadow-2xl border border-[var(--border)] z-40 flex flex-col overflow-hidden animate-in slide-in-from-right-8 duration-200">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-200 bg-slate-50/80 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 border border-indigo-200">
              {data.nodeType.replace(/_/g, ' ')}
            </span>
            {data.isStart && (
              <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200">
                START NODE
              </span>
            )}
            {data.isEnd && (
              <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800 border border-indigo-200">
                END NODE
              </span>
            )}
            <span className="text-[10px] font-mono text-slate-500 bg-white px-1.5 py-0.5 rounded border border-slate-200 ml-auto">
              ID: {data.id}
            </span>
          </div>
          <h2 className="text-base font-bold text-slate-900 break-words leading-tight">{data.label}</h2>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors flex-shrink-0"
          title="Close config panel"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Description */}
      {data.description && (
        <div className="px-5 py-3 bg-indigo-50/40 border-b border-indigo-100/50">
          <p className="text-xs text-slate-600 leading-relaxed">{data.description}</p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-[var(--border)] bg-slate-100/60 px-3 pt-2 gap-1 text-xs">
        <button
          onClick={() => setActiveTab('config')}
          className={`px-3 py-1.5 rounded-t-lg font-medium transition-colors ${
            activeTab === 'config'
              ? 'bg-white text-indigo-600 border-t border-x border-[var(--border)] shadow-xs'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          ⚙️ Configuration ({configKeys.length})
        </button>
        <button
          onClick={() => setActiveTab('ports')}
          className={`px-3 py-1.5 rounded-t-lg font-medium transition-colors ${
            activeTab === 'ports'
              ? 'bg-white text-indigo-600 border-t border-x border-[var(--border)] shadow-xs'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          🔌 Ports
        </button>
        {data.tool && (
          <button
            onClick={() => setActiveTab('tool')}
            className={`px-3 py-1.5 rounded-t-lg font-medium transition-colors ${
              activeTab === 'tool'
                ? 'bg-white text-indigo-600 border-t border-x border-[var(--border)] shadow-xs'
                : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            🛠️ Tool
          </button>
        )}
        <button
          onClick={() => setActiveTab('raw')}
          className={`px-3 py-1.5 rounded-t-lg font-medium transition-colors ${
            activeTab === 'raw'
              ? 'bg-white text-indigo-600 border-t border-x border-[var(--border)] shadow-xs'
              : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          {'{ }'} Raw
        </button>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {/* TAB 1: Configuration Fields */}
        {activeTab === 'config' && (
          <div className="space-y-4">
            {/* Node Label Editing */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Step Label</label>
              <input
                type="text"
                value={nodeLabel}
                onChange={(e) => {
                  setNodeLabel(e.target.value);
                  setIsSaved(false);
                }}
                className="w-full text-xs px-3 py-2 bg-slate-50 border border-[var(--border)] rounded-lg focus:outline-none focus:border-indigo-500 focus:bg-white"
              />
              <p className="text-[10px] text-slate-400 mt-1">Display label shown on the canvas node.</p>
            </div>

            {/* Config Fields Header */}
            <div className="pt-2 border-t border-slate-100">
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider mb-2 flex items-center justify-between">
                <span>Required Execution Parameters</span>
                <span className="text-[10px] text-slate-400 font-normal lowercase">
                  {configKeys.length} field{configKeys.length === 1 ? '' : 's'}
                </span>
              </h3>

              {configKeys.length === 0 ? (
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl text-center text-xs text-slate-500">
                  <p className="font-medium">No custom configuration parameters</p>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    This node executes using standard default runtime inputs.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {configKeys.map((key) => {
                    const val = configValues[key];
                    const explanation =
                      FIELD_EXPLANATIONS[key] ||
                      `Configures the ${key.replace(/_/g, ' ')} for this step.`;
                    const isLongText = typeof val === 'string' && val.length > 40;
                    const isObject = typeof val === 'object' && val !== null;

                    return (
                      <div key={key} className="bg-slate-50 p-3 rounded-xl border border-slate-200/80">
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-xs font-semibold font-mono text-indigo-700">{key}</label>
                          <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-slate-200 text-slate-600">
                            {Array.isArray(val) ? 'array' : typeof val}
                          </span>
                        </div>

                        {/* Explanation of what this field needs to run */}
                        <p className="text-[11px] text-slate-600 mb-2 leading-tight">{explanation}</p>

                        {/* Input widget */}
                        {isObject ? (
                          <textarea
                            rows={3}
                            value={JSON.stringify(val, null, 2)}
                            onChange={(e) => {
                              try {
                                handleConfigChange(key, JSON.parse(e.target.value));
                              } catch {
                                // Keep typing
                              }
                            }}
                            className="w-full text-xs font-mono p-2 bg-white border border-slate-300 rounded-lg focus:outline-none focus:border-indigo-500"
                          />
                        ) : isLongText ? (
                          <textarea
                            rows={2}
                            value={String(val)}
                            onChange={(e) => handleConfigChange(key, e.target.value)}
                            className="w-full text-xs p-2 bg-white border border-slate-300 rounded-lg focus:outline-none focus:border-indigo-500"
                          />
                        ) : typeof val === 'number' ? (
                          <input
                            type="number"
                            value={val}
                            onChange={(e) => handleConfigChange(key, parseFloat(e.target.value) || 0)}
                            className="w-full text-xs px-2.5 py-1.5 bg-white border border-slate-300 rounded-lg focus:outline-none focus:border-indigo-500"
                          />
                        ) : typeof val === 'boolean' ? (
                          <select
                            value={String(val)}
                            onChange={(e) => handleConfigChange(key, e.target.value === 'true')}
                            className="w-full text-xs px-2.5 py-1.5 bg-white border border-slate-300 rounded-lg focus:outline-none focus:border-indigo-500"
                          >
                            <option value="true">True</option>
                            <option value="false">False</option>
                          </select>
                        ) : (
                          <input
                            type="text"
                            value={String(val ?? '')}
                            onChange={(e) => handleConfigChange(key, e.target.value)}
                            className="w-full text-xs px-2.5 py-1.5 bg-white border border-slate-300 rounded-lg focus:outline-none focus:border-indigo-500"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Execution Requirements Info Box */}
            <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-xl text-xs text-amber-900 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold">
                <span>⚡ Runtime Requirements</span>
              </div>
              <p className="text-[11px] text-amber-800 leading-relaxed">
                {data.tool
                  ? `To execute this node, the '${data.tool.name}' connector must be authenticated with appropriate API scopes for '${data.tool.operation}'.`
                  : data.nodeType.includes('llm') || data.nodeType.includes('ai')
                  ? 'Requires a configured Gemini / LLM API key with active generation quota.'
                  : data.nodeType.includes('database')
                  ? 'Requires database host credentials and valid table read/write permissions.'
                  : 'Requires valid JSON payload from upstream connecting nodes.'}
              </p>
            </div>
          </div>
        )}

        {/* TAB 2: Input & Output Ports */}
        {activeTab === 'ports' && (
          <div className="space-y-4">
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-blue-500" />
                Input Data Ports (Expected from Upstream)
              </h4>
              {registryNode?.inputs && registryNode.inputs.length > 0 ? (
                <div className="space-y-2">
                  {registryNode.inputs.map((port) => (
                    <div key={port.id} className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-xs">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-semibold text-slate-800">{port.name}</span>
                        <span className="text-[10px] font-mono text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">
                          {port.data_type}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 leading-tight">
                        {port.description || 'Payload received from previous step.'}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400 italic bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                  {data.isStart ? 'No inputs needed — this is an initial trigger node.' : 'Standard input context accepted.'}
                </p>
              )}
            </div>

            <div className="pt-2 border-t border-slate-100">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-700 mb-2 flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                Output Data Ports (Emitted to Downstream)
              </h4>
              {registryNode?.outputs && registryNode.outputs.length > 0 ? (
                <div className="space-y-2">
                  {registryNode.outputs.map((port) => (
                    <div key={port.id} className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-xs">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-semibold text-slate-800">{port.name}</span>
                        <span className="text-[10px] font-mono text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                          {port.data_type}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 leading-tight">
                        {port.description || 'Emitted downstream to dependent nodes.'}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400 italic bg-slate-50 p-2.5 rounded-lg border border-slate-200">
                  {data.isEnd ? 'No downstream outputs — this is a terminal end node.' : 'Standard output context emitted.'}
                </p>
              )}
            </div>
          </div>
        )}

        {/* TAB 3: Tool & Service Integration */}
        {activeTab === 'tool' && data.tool && (
          <div className="space-y-3">
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-slate-900">{data.tool.name}</h4>
                  <p className="text-xs font-mono text-indigo-600">{data.tool.operation}</p>
                </div>
                <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />
                  {data.tool.status || 'not_connected'}
                </span>
              </div>

              <div className="text-xs text-slate-600 space-y-1.5 pt-2 border-t border-slate-200">
                <p>
                  <strong>Service Provider:</strong> {data.tool.name}
                </p>
                <p>
                  <strong>Invoked Action:</strong> <code className="text-slate-800">{data.tool.operation}</code>
                </p>
                <p>
                  <strong>Authentication:</strong> OAuth 2.0 / API Key required at runtime
                </p>
              </div>
            </div>

            <div className="p-3 bg-blue-50 border border-blue-200 rounded-xl text-xs text-blue-900">
              <p className="font-semibold mb-1">🔗 Integration Layer Status</p>
              <p className="text-[11px] text-blue-800 leading-relaxed">
                External tools are configured in design mode. In Phase 11 (Composio Integration Layer), clicking
                &ldquo;Connect&rdquo; will initiate the OAuth handshake for live execution.
              </p>
            </div>
          </div>
        )}

        {/* TAB 4: Raw JSON View */}
        {activeTab === 'raw' && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span>Node Schema JSON</span>
              <button
                onClick={() => navigator.clipboard.writeText(JSON.stringify(node.data, null, 2))}
                className="text-[10px] text-indigo-600 hover:text-indigo-800 font-medium"
              >
                Copy to Clipboard
              </button>
            </div>
            <pre className="text-[11px] font-mono p-3 bg-slate-900 text-emerald-400 rounded-xl overflow-x-auto max-h-[360px] leading-relaxed">
              {JSON.stringify(
                {
                  id: data.id,
                  type: data.nodeType,
                  label: nodeLabel,
                  description: data.description,
                  config: configValues,
                  tool: data.tool,
                  isStart: data.isStart,
                  isEnd: data.isEnd,
                },
                null,
                2
              )}
            </pre>
          </div>
        )}
      </div>

      {/* Footer / Actions */}
      <div className="px-5 py-3 border-t border-[var(--border)] bg-slate-50/70 flex items-center justify-between gap-2">
        <span className="text-xs text-slate-500">
          {isSaved ? <span className="text-emerald-600 font-semibold">✓ Configuration Updated</span> : 'Click node to deselect'}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:text-slate-800 rounded-lg hover:bg-slate-200 transition-colors"
          >
            Close
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-1.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors shadow-sm"
          >
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}
