"""Removed (legacy) node types: identification data only.

Milestone 2 removed every design-only node type from the active registry.
Workflows saved earlier may still contain them. This module lets the planner,
the API and the editor *identify* such nodes and explain what to do. It never
maps a legacy node to an executable operation: legacy nodes keep their
original type/operation, config and connections and are always rejected
before execution.
"""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel

UNSUPPORTED_PREFIX = "unsupported:"  # re-exported by app.services.workflow_upgrade


class LegacyNodeType(BaseModel):
    node_type: str
    label: str
    category: str
    description: str
    reason: str
    replacement: Optional[str] = None  # human advice, never applied automatically


def _l(node_type: str, label: str, category: str, description: str, reason: str,
       replacement: Optional[str] = None) -> LegacyNodeType:
    return LegacyNodeType(node_type=node_type, label=label, category=category, description=description,
                          reason=reason, replacement=replacement)


_INTEGRATION = "Application integrations are not available yet (planned for Milestone 3)."

LEGACY_NODE_TYPES: Dict[str, LegacyNodeType] = {n.node_type: n for n in [
    _l("schedule_trigger", "Schedule Trigger (legacy)", "input_output",
       "Fires periodically based on a cron expression or interval.",
       "The legacy design-only schedule node never executed.",
       "Replace it with the executable Schedule Trigger (core.schedule_trigger)."),
    _l("email_trigger", "Inbound Email Trigger", "input_output",
       "Listens for incoming emails matching filters.", _INTEGRATION,
       "Use a Webhook Trigger or Form Trigger for now."),
    _l("webhook_output", "HTTP / Webhook Response", "input_output",
       "Returns an HTTP response to the caller or dispatches an outbound webhook.",
       "Synchronous webhook responses are not supported.",
       "To call another system use HTTP Request; to finish a path use End."),
    _l("email_output", "Send Email", "input_output", "Composes and sends an email.", _INTEGRATION,
       "Use HTTP Request against your email provider's API."),
    _l("notification_output", "Push Notification / Alert", "input_output",
       "Broadcasts alerts to Slack, Discord or SMS.", _INTEGRATION,
       "Use HTTP Request against the service's webhook URL."),
    _l("llm_agent", "AI Agent / LLM Reasoning (legacy)", "ai_agent",
       "Generative reasoning and instruction following.", "The legacy design-only AI node never executed.",
       "Replace it with the AI Agent (ai.agent) or AI Generate (ai.generate)."),
    _l("text_classifier", "Intent & Category Classifier (legacy)", "ai_agent",
       "Categorizes text into predefined classes.", "The legacy design-only AI node never executed.",
       "Replace it with AI Generate (ai.generate) and an output schema with an enum."),
    _l("entity_extractor", "Entity & Data Extractor (legacy)", "ai_agent",
       "Extracts structured entities from text.", "The legacy design-only AI node never executed.",
       "Replace it with AI Generate (ai.generate) and a structured output schema."),
    _l("summarizer", "Document & Text Summarizer (legacy)", "ai_agent",
       "Summarizes long text.", "The legacy design-only AI node never executed.",
       "Replace it with AI Generate (ai.generate)."),
    _l("database_query", "Database Query (Read)", "tools", "Queries database tables.",
       "No database connector exists.", "Query your database's HTTP API with HTTP Request."),
    _l("database_update", "Database Write / Mutate", "tools", "Writes records to a database.",
       "No database connector exists.", "Call your database's HTTP API with HTTP Request."),
    _l("file_operation", "File & Document Storage", "tools", "Reads or writes files.",
       "No storage connector exists.", None),
    _l("tool_integration", "External Service Tool", "tools", "Invokes third-party SaaS actions.",
       _INTEGRATION, "Use HTTP Request against the service's API."),
    _l("switch", "Multi-Way Switch / Router (legacy)", "logic", "Routes execution to one of several paths.",
       "The legacy design-only switch never executed.", "Replace it with the executable Switch (core.switch)."),
    _l("loop", "Loop / For-Each Iterator (legacy)", "logic", "Iterates over an array of items.",
       "The legacy design-only loop never executed.",
       "Replace it with the executable Loop Over Items (core.loop)."),
    _l("error_handler", "Error / Exception Handler", "logic", "Catches failures in upstream nodes.",
       "Error routes are not supported.", "Set the failing node's 'On error' setting to 'Continue'."),
    _l("code_execution", "Custom Script Execution", "data_processing", "Runs a custom script.",
       "Executing arbitrary code is not allowed on this platform.",
       "Use Set, Transform, Filter, Date & Time or Array operations instead."),
    _l("vector_search", "Vector Semantic Search", "memory_knowledge", "Vector similarity search.",
       "No vector store exists.", None),
    _l("knowledge_retrieval", "Knowledge Base Lookup", "memory_knowledge", "Looks up knowledge bases.",
       "No knowledge store exists.", "Query your knowledge base's HTTP API with HTTP Request."),
    _l("human_approval", "Human-in-the-Loop Approval", "human_in_the_loop", "Pauses for manual sign-off.",
       "Durable pause/resume and approvals are planned for Milestone 4.", None),
    _l("merge", "Merge (legacy)", "data_processing", "Combines data from several branches.",
       "The legacy design-only merge never executed.", "Replace it with the executable Merge (core.merge)."),
    _l("wait", "Wait", "logic", "Pauses execution for a duration or event.",
       "Durable waits are planned for Milestone 4.", None),
    _l("parallel_branch", "Parallel Branch", "logic", "Runs branches concurrently.",
       "The engine executes branches sequentially; parallel branches are not supported.",
       "Connect several nodes to the same output; they run one after another."),
    _l("join", "Join", "logic", "Waits for parallel branches.",
       "The engine executes branches sequentially; joins are not supported.",
       "Use the executable Merge (core.merge) to combine branch outputs."),
]}


def legacy_type_of(operation: Optional[str], node_type: Optional[str] = None) -> Optional[str]:
    """The removed node type a canonical node refers to, if any."""
    candidates = []
    if operation:
        candidates.append(operation[len(UNSUPPORTED_PREFIX):] if operation.startswith(UNSUPPORTED_PREFIX)
                          else operation)
    if node_type:
        candidates.append(node_type)
    for c in candidates:
        if c and c.strip().lower() in LEGACY_NODE_TYPES:
            return c.strip().lower()
    return None


def legacy_message(node_label: str, legacy_type: str) -> tuple[str, str]:
    """(message, suggestion) explaining a removed node type and how to proceed."""
    info = LEGACY_NODE_TYPES[legacy_type]
    message = (f"Node {node_label} uses '{info.label}' ({legacy_type}), a node type that was removed from the "
               f"library because it could not execute. {info.reason}")
    suggestion = (f"{info.replacement + ' ' if info.replacement else ''}Its original configuration and "
                  "connections are preserved; edit or replace the node, or delete it, to run this workflow.")
    return message, suggestion
