"""Node Registry implementation for managing, discovering, and injecting node knowledge."""

from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.schemas.registry import (
    NodeCategory,
    NodeDefinition,
    PortDataType,
    PortDefinition,
    PortType,
    ToolDefinition,
)


class NodeRegistry:
    """In-memory registry of supported workflow node definitions."""

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeDefinition] = {}

    def register(self, definition: NodeDefinition) -> None:
        """Register a new node definition."""
        self._nodes[definition.node_type] = definition

    def get(self, node_type: str) -> Optional[NodeDefinition]:
        """Look up a node definition by its unique type name."""
        return self._nodes.get(node_type.strip().lower())

    def list_all(self) -> List[NodeDefinition]:
        """Return all registered node definitions."""
        return list(self._nodes.values())

    def list_by_category(self, category: NodeCategory | str) -> List[NodeDefinition]:
        """Return node definitions belonging to a specific category."""
        target = category.value if isinstance(category, NodeCategory) else str(category).lower()
        return [node for node in self._nodes.values() if node.category.value == target]

    def get_categories(self) -> List[str]:
        """Return list of distinct categories currently present in registry."""
        return sorted({node.category.value for node in self._nodes.values()})

    def get_catalog_for_prompt(self) -> str:
        """Format a concise, token-efficient knowledge representation of the registry for LLM system prompts."""
        lines = [
            "STANDARD NODE REGISTRY (Use these standard node types when designing workflows):",
            "Categories and available node types:",
        ]

        # Group by category
        grouped: Dict[str, List[NodeDefinition]] = {}
        for node in self._nodes.values():
            cat = node.category.value
            grouped.setdefault(cat, []).append(node)

        for cat, nodes in sorted(grouped.items()):
            lines.append(f"\n### Category: {cat.upper().replace('_', ' ')}")
            for node in nodes:
                tools_str = ""
                if node.compatible_tools:
                    tool_names = ", ".join(sorted({t.name for t in node.compatible_tools}))
                    tools_str = f" [Compatible tools: {tool_names}]"
                in_ports = ", ".join(p.name for p in node.inputs) or "none"
                out_ports = ", ".join(p.name for p in node.outputs) or "none"
                lines.append(
                    f"- `{node.node_type}` ({node.label}): {node.description}{tools_str} "
                    f"| Inputs: [{in_ports}] -> Outputs: [{out_ports}]"
                )

        lines.append(
            "\nREGISTRY USAGE RULES:\n"
            "1. When an operation matches a registered node type, use the exact `type` string above.\n"
            "2. If an external service is needed (e.g. Gmail, Slack, Stripe, Jira, GitHub, PostgreSQL), "
            "set `tool`: {\"name\": \"<Service>\", \"operation\": \"<action>\", \"status\": \"not_connected\"}.\n"
            "3. If a novel or domain-specific requirement cannot be cleanly represented by the registry, "
            "you may invent a descriptive snake_case `type` (e.g., `document_ocr`, `compliance_validator`), "
            "following the same input/output and tool patterns."
        )
        return "\n".join(lines)

    def get_catalog_dict(self) -> Dict[str, Any]:
        """Return full catalog serializable to JSON for API consumers."""
        return {
            "total_nodes": len(self._nodes),
            "categories": self.get_categories(),
            "nodes": [node.model_dump() for node in self._nodes.values()],
        }


def _create_standard_registry() -> NodeRegistry:
    """Populates and returns the comprehensive standard node catalog."""
    registry = NodeRegistry()

    # ==========================================
    # 1. INPUT / OUTPUT (TRIGGERS & TERMINALS)
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="webhook_trigger",
            label="Webhook Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Receives real-time incoming HTTP requests/payloads from external systems.",
            inputs=[],
            outputs=[
                PortDefinition(id="out_payload", name="Payload", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Parsed JSON payload body"),
                PortDefinition(id="out_headers", name="Headers", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Request HTTP headers"),
            ],
            default_config={"method": "POST", "path": "/webhook/v1"},
            icon="webhook",
            tags=["trigger", "webhook", "http", "api", "ingress"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="schedule_trigger",
            label="Schedule Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Fires periodically based on a cron expression, interval timer, or recurring calendar schedule.",
            inputs=[],
            outputs=[
                PortDefinition(id="out_timestamp", name="Trigger Time", port_type=PortType.OUTPUT, data_type=PortDataType.STRING, description="ISO timestamp of trigger run"),
            ],
            default_config={"cron": "0 9 * * 1-5", "timezone": "UTC"},
            icon="clock",
            tags=["trigger", "schedule", "cron", "timer", "interval"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="email_trigger",
            label="Inbound Email Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Listens for incoming emails matching filters (subject, sender, labels, attachments).",
            inputs=[],
            outputs=[
                PortDefinition(id="out_email", name="Email Message", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Structured email with sender, subject, body, attachments"),
            ],
            default_config={"inbox": "support@company.com", "filter": "is:unread"},
            compatible_tools=[
                ToolDefinition(name="Gmail", operation="watch_inbox", description="Monitors Gmail account inbox for incoming messages"),
                ToolDefinition(name="Outlook", operation="watch_folder", description="Monitors Outlook email folder"),
            ],
            icon="mail",
            tags=["trigger", "email", "gmail", "outlook", "inbox"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="manual_trigger",
            label="Manual / Form Trigger",
            category=NodeCategory.INPUT_OUTPUT,
            description="Initiated on demand by a human user or through a custom web form submission.",
            inputs=[],
            outputs=[
                PortDefinition(id="out_form_data", name="Form Data", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Submitted form field values"),
            ],
            default_config={"require_auth": True},
            icon="play",
            tags=["trigger", "manual", "form", "user_input"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="webhook_output",
            label="HTTP / Webhook Response",
            category=NodeCategory.INPUT_OUTPUT,
            description="Returns an HTTP response to caller or dispatches an outbound webhook payload.",
            inputs=[
                PortDefinition(id="in_response_body", name="Response Body", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Data to return or dispatch"),
            ],
            outputs=[],
            default_config={"status_code": 200, "content_type": "application/json"},
            icon="arrow-up-right",
            tags=["output", "http", "response", "webhook"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="email_output",
            label="Send Email",
            category=NodeCategory.INPUT_OUTPUT,
            description="Composes and sends an email message to specified recipients.",
            inputs=[
                PortDefinition(id="in_recipient", name="Recipient", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Recipient email address"),
                PortDefinition(id="in_content", name="Message Body", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="HTML or plain text content"),
            ],
            outputs=[
                PortDefinition(id="out_status", name="Send Status", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Dispatch status and message ID"),
            ],
            default_config={"subject_template": "Workflow Notification"},
            compatible_tools=[
                ToolDefinition(name="Gmail", operation="send_email", description="Sends message via Gmail API"),
                ToolDefinition(name="SendGrid", operation="send_email", description="Dispatches transactional email via SendGrid"),
            ],
            icon="mail-send",
            tags=["output", "email", "gmail", "sendgrid", "notification"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="notification_output",
            label="Push Notification / Alert",
            category=NodeCategory.INPUT_OUTPUT,
            description="Broadcasts real-time alerts to collaboration channels like Slack, Discord, or SMS.",
            inputs=[
                PortDefinition(id="in_alert_text", name="Alert Message", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Message to post"),
            ],
            outputs=[
                PortDefinition(id="out_delivery", name="Delivery Receipt", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Channel message reference"),
            ],
            default_config={"channel": "#general"},
            compatible_tools=[
                ToolDefinition(name="Slack", operation="post_message", description="Posts chat message to Slack channel"),
                ToolDefinition(name="Discord", operation="post_webhook", description="Dispatches embed to Discord channel"),
                ToolDefinition(name="Twilio", operation="send_sms", description="Sends SMS text alert"),
            ],
            icon="bell",
            tags=["output", "notification", "slack", "discord", "sms", "alert"],
        )
    )

    # ==========================================
    # 2. AI / AGENT NODES
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="llm_agent",
            label="AI Agent / LLM Reasoning",
            category=NodeCategory.AI_AGENT,
            description="Executes generative reasoning, natural-language generation, decision-making, or complex instruction following.",
            inputs=[
                PortDefinition(id="in_prompt", name="Prompt Context", port_type=PortType.INPUT, data_type=PortDataType.ANY, description="Context, instructions, and input variables"),
            ],
            outputs=[
                PortDefinition(id="out_response", name="AI Response", port_type=PortType.OUTPUT, data_type=PortDataType.STRING, description="Generated text, summary, or structured reasoning"),
            ],
            default_config={"model": "gemini-3.8-flash", "temperature": 0.2, "system_instruction": "You are a helpful assistant."},
            icon="sparkles",
            tags=["ai", "llm", "agent", "reasoning", "gemini", "gpt"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="text_classifier",
            label="Intent & Category Classifier",
            category=NodeCategory.AI_AGENT,
            description="Categorizes text into predefined classes (e.g. sentiment, urgency tier, customer intent, inquiry topic).",
            inputs=[
                PortDefinition(id="in_text", name="Input Text", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Text to classify"),
            ],
            outputs=[
                PortDefinition(id="out_category", name="Predicted Category", port_type=PortType.OUTPUT, data_type=PortDataType.STRING, description="Assigned category label"),
                PortDefinition(id="out_confidence", name="Confidence", port_type=PortType.OUTPUT, data_type=PortDataType.NUMBER, description="Confidence score between 0.0 and 1.0"),
            ],
            default_config={"categories": ["Billing", "Technical Support", "Sales", "General Inquiry"]},
            icon="tag",
            tags=["ai", "classification", "sentiment", "intent", "categorize"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="entity_extractor",
            label="Entity & Data Extractor",
            category=NodeCategory.AI_AGENT,
            description="Extracts structured entities, key-value pairs, dates, amounts, and IDs from unstructured text or documents.",
            inputs=[
                PortDefinition(id="in_document", name="Unstructured Text", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Document or message text to parse"),
            ],
            outputs=[
                PortDefinition(id="out_entities", name="Extracted JSON", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Structured dictionary of extracted entities"),
            ],
            default_config={"target_schema": {"order_id": "string", "amount": "number", "vendor": "string"}},
            icon="scan",
            tags=["ai", "extraction", "ner", "entities", "parser"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="summarizer",
            label="Document & Text Summarizer",
            category=NodeCategory.AI_AGENT,
            description="Distills lengthy articles, meeting notes, email threads, or reports into concise executive summaries.",
            inputs=[
                PortDefinition(id="in_content", name="Long Content", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Content to summarize"),
            ],
            outputs=[
                PortDefinition(id="out_summary", name="Summary", port_type=PortType.OUTPUT, data_type=PortDataType.STRING, description="Concise bullet points or executive overview"),
            ],
            default_config={"format": "bullet_points", "max_length": 300},
            icon="file-text",
            tags=["ai", "summarize", "synthesis", "overview"],
        )
    )

    # ==========================================
    # 3. TOOLS & INTEGRATIONS
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="api_call",
            label="HTTP / REST API Call",
            category=NodeCategory.TOOLS,
            description="Makes arbitrary HTTP requests (GET, POST, PUT, DELETE) to any external REST endpoint.",
            inputs=[
                PortDefinition(id="in_params", name="Request Parameters", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Query params, body payload, or auth tokens"),
            ],
            outputs=[
                PortDefinition(id="out_response", name="Response Data", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="JSON response payload"),
                PortDefinition(id="out_status_code", name="Status Code", port_type=PortType.OUTPUT, data_type=PortDataType.NUMBER, description="HTTP response status code"),
            ],
            default_config={"method": "GET", "url": "https://api.example.com/v1/resource"},
            icon="globe",
            tags=["tools", "api", "rest", "http", "fetch"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="database_query",
            label="Database Query (Read)",
            category=NodeCategory.TOOLS,
            description="Queries SQL or NoSQL database tables to retrieve records matching criteria.",
            inputs=[
                PortDefinition(id="in_query_params", name="Filter Parameters", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Dynamic query filter parameters"),
            ],
            outputs=[
                PortDefinition(id="out_records", name="Query Records", port_type=PortType.OUTPUT, data_type=PortDataType.ARRAY, description="List of matching database rows"),
            ],
            default_config={"query": "SELECT * FROM orders WHERE id = :order_id", "timeout_sec": 10},
            compatible_tools=[
                ToolDefinition(name="PostgreSQL", operation="select_query", description="Executes SELECT query on PostgreSQL"),
                ToolDefinition(name="MySQL", operation="select_query", description="Executes SELECT query on MySQL"),
                ToolDefinition(name="MongoDB", operation="find", description="Queries MongoDB collection documents"),
            ],
            icon="database",
            tags=["tools", "database", "sql", "postgres", "mysql", "mongo", "query"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="database_update",
            label="Database Write / Mutate",
            category=NodeCategory.TOOLS,
            description="Inserts, updates, or deletes records in a target database.",
            inputs=[
                PortDefinition(id="in_record", name="Record Data", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Data to insert or update"),
            ],
            outputs=[
                PortDefinition(id="out_result", name="Mutation Result", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Affected rows count and primary keys"),
            ],
            default_config={"table": "orders", "operation": "UPDATE"},
            compatible_tools=[
                ToolDefinition(name="PostgreSQL", operation="upsert_row", description="Upserts record into PostgreSQL table"),
                ToolDefinition(name="MongoDB", operation="insert_one", description="Inserts document into MongoDB"),
            ],
            icon="save",
            tags=["tools", "database", "insert", "update", "write"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="file_operation",
            label="File & Document Storage",
            category=NodeCategory.TOOLS,
            description="Reads, writes, parses, or uploads files to cloud storage or local disk.",
            inputs=[
                PortDefinition(id="in_file_content", name="File Data", port_type=PortType.INPUT, data_type=PortDataType.ANY, description="Bytes or stream to persist"),
            ],
            outputs=[
                PortDefinition(id="out_file_url", name="File URL", port_type=PortType.OUTPUT, data_type=PortDataType.STRING, description="Accessible storage URL or path"),
            ],
            default_config={"storage_provider": "S3", "bucket": "company-assets"},
            compatible_tools=[
                ToolDefinition(name="GoogleDrive", operation="upload_file", description="Uploads file to Google Drive folder"),
                ToolDefinition(name="AWS_S3", operation="put_object", description="Puts object into S3 bucket"),
            ],
            icon="file",
            tags=["tools", "file", "s3", "gdrive", "storage", "pdf"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="tool_integration",
            label="External Service Tool",
            category=NodeCategory.TOOLS,
            description="Connects to 3rd-party SaaS platforms (Slack, Jira, GitHub, Stripe, Notion, Composio) to invoke actions.",
            inputs=[
                PortDefinition(id="in_action_params", name="Action Payload", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Parameters required by target service"),
            ],
            outputs=[
                PortDefinition(id="out_action_result", name="Action Response", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Result returned by external service"),
            ],
            default_config={"service_name": "Slack", "operation": "post_message"},
            compatible_tools=[
                ToolDefinition(name="Slack", operation="post_message", description="Posts chat message to channel"),
                ToolDefinition(name="Jira", operation="create_issue", description="Creates tracking ticket in Jira"),
                ToolDefinition(name="GitHub", operation="create_pull_request", description="Opens pull request on repository"),
                ToolDefinition(name="Stripe", operation="create_payout", description="Creates payment or payout transfer"),
                ToolDefinition(name="Notion", operation="create_page", description="Adds record or page to Notion database"),
            ],
            icon="plug",
            tags=["tools", "saas", "slack", "jira", "github", "stripe", "notion", "composio"],
        )
    )

    # ==========================================
    # 4. LOGIC & FLOW CONTROL
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="condition",
            label="Conditional Branch (If/Else)",
            category=NodeCategory.LOGIC,
            description="Evaluates a boolean condition expression and routes workflow execution to true/false paths.",
            inputs=[
                PortDefinition(id="in_val", name="Evaluation Input", port_type=PortType.INPUT, data_type=PortDataType.ANY, description="Value or object evaluated in condition"),
            ],
            outputs=[
                PortDefinition(id="out_true", name="True (Yes)", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Fires when condition evaluates to true"),
                PortDefinition(id="out_false", name="False (No)", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Fires when condition evaluates to false"),
            ],
            default_config={"expression": "amount > 5000"},
            icon="git-branch",
            tags=["logic", "condition", "branch", "if", "decision"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="switch",
            label="Multi-Way Switch / Router",
            category=NodeCategory.LOGIC,
            description="Routes execution to one of multiple target paths depending on an evaluated key or status code.",
            inputs=[
                PortDefinition(id="in_key", name="Switch Key", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Key or enum evaluated against cases"),
            ],
            outputs=[
                PortDefinition(id="out_case_1", name="Case 1", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Match path 1"),
                PortDefinition(id="out_case_2", name="Case 2", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Match path 2"),
                PortDefinition(id="out_default", name="Default", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Fallback if no case matched"),
            ],
            default_config={"cases": ["active", "pending", "cancelled"]},
            icon="git-merge",
            tags=["logic", "switch", "route", "multiplexer", "dispatch"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="loop",
            label="Loop / For-Each Iterator",
            category=NodeCategory.LOGIC,
            description="Iterates sequentially or in parallel over an array of items, running downstream operations for each.",
            inputs=[
                PortDefinition(id="in_items", name="Item Array", port_type=PortType.INPUT, data_type=PortDataType.ARRAY, description="Array of items to iterate over"),
            ],
            outputs=[
                PortDefinition(id="out_item", name="Current Item", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Single item for current iteration"),
                PortDefinition(id="out_completed", name="All Done", port_type=PortType.OUTPUT, data_type=PortDataType.ARRAY, description="Fires after all iterations complete"),
            ],
            default_config={"batch_size": 1, "concurrency": 1},
            icon="repeat",
            tags=["logic", "loop", "iterator", "for_each", "batch"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="error_handler",
            label="Error / Exception Handler",
            category=NodeCategory.LOGIC,
            description="Catches failures or timeouts in upstream nodes, enabling resilient recovery or rollback paths.",
            inputs=[
                PortDefinition(id="in_error", name="Error Context", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Exception details and node ID"),
            ],
            outputs=[
                PortDefinition(id="out_handled", name="Recovery Path", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Downstream fallback execution"),
            ],
            default_config={"retry_attempts": 3, "retry_delay_sec": 5},
            icon="alert-triangle",
            tags=["logic", "error", "catch", "fallback", "retry", "resilience"],
        )
    )

    # ==========================================
    # 5. DATA PROCESSING
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="data_transform",
            label="Data Transform / JSON Mapper",
            category=NodeCategory.DATA_PROCESSING,
            description="Maps, reshapes, cleans, or transforms JSON data structure between incompatible node formats.",
            inputs=[
                PortDefinition(id="in_raw_data", name="Raw Data", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Input structure to transform"),
            ],
            outputs=[
                PortDefinition(id="out_transformed", name="Transformed Data", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Cleaned and restructured output"),
            ],
            default_config={"mapping": {"id": "data.order_id", "email": "data.customer.email"}},
            icon="shuffle",
            tags=["data", "transform", "mapping", "json", "format"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="filter",
            label="Data Filter",
            category=NodeCategory.DATA_PROCESSING,
            description="Filters a list of items or messages based on attribute predicates, removing non-matching elements.",
            inputs=[
                PortDefinition(id="in_items", name="Item List", port_type=PortType.INPUT, data_type=PortDataType.ARRAY, description="Input array to filter"),
            ],
            outputs=[
                PortDefinition(id="out_passed", name="Passed Items", port_type=PortType.OUTPUT, data_type=PortDataType.ARRAY, description="Items matching filter criteria"),
            ],
            default_config={"predicate": "item.status == 'approved'"},
            icon="filter",
            tags=["data", "filter", "predicate", "clean"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="code_execution",
            label="Custom Script Execution",
            category=NodeCategory.DATA_PROCESSING,
            description="Executes a safe sandboxed Python or JavaScript script for specialized mathematical, parsing, or data operations.",
            inputs=[
                PortDefinition(id="in_args", name="Script Arguments", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Input variables dictionary"),
            ],
            outputs=[
                PortDefinition(id="out_return", name="Return Value", port_type=PortType.OUTPUT, data_type=PortDataType.ANY, description="Script return value"),
            ],
            default_config={"language": "python", "timeout_sec": 5},
            icon="code",
            tags=["data", "code", "python", "javascript", "script", "sandbox"],
        )
    )

    # ==========================================
    # 6. MEMORY & KNOWLEDGE
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="vector_search",
            label="Vector Semantic Search",
            category=NodeCategory.MEMORY_KNOWLEDGE,
            description="Performs dense vector similarity search against a vector database for RAG retrieval or semantic matching.",
            inputs=[
                PortDefinition(id="in_query", name="Query Text", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Search query or question"),
            ],
            outputs=[
                PortDefinition(id="out_matches", name="Relevant Chunks", port_type=PortType.OUTPUT, data_type=PortDataType.ARRAY, description="Top K most similar text chunks and scores"),
            ],
            default_config={"top_k": 5, "collection": "knowledge_base", "similarity_threshold": 0.75},
            compatible_tools=[
                ToolDefinition(name="Qdrant", operation="search_collection", description="Semantic search on Qdrant"),
                ToolDefinition(name="Pinecone", operation="query_index", description="Queries Pinecone vector index"),
            ],
            icon="search",
            tags=["memory", "vector", "search", "rag", "qdrant", "pinecone", "embeddings"],
        )
    )

    registry.register(
        NodeDefinition(
            node_type="knowledge_retrieval",
            label="Knowledge Base Lookup",
            category=NodeCategory.MEMORY_KNOWLEDGE,
            description="Retrieves company policies, FAQs, product catalogs, or user memory from structured knowledge bases.",
            inputs=[
                PortDefinition(id="in_topic", name="Search Topic", port_type=PortType.INPUT, data_type=PortDataType.STRING, description="Keyword or lookup topic"),
            ],
            outputs=[
                PortDefinition(id="out_docs", name="Retrieved Documents", port_type=PortType.OUTPUT, data_type=PortDataType.ARRAY, description="Retrieved documentation articles"),
            ],
            default_config={"source": "company_docs"},
            compatible_tools=[
                ToolDefinition(name="Notion", operation="search_pages", description="Searches Notion workspace documents"),
            ],
            icon="book-open",
            tags=["memory", "knowledge", "docs", "retrieval", "faq"],
        )
    )

    # ==========================================
    # 7. HUMAN IN THE LOOP
    # ==========================================
    registry.register(
        NodeDefinition(
            node_type="human_approval",
            label="Human-in-the-Loop Approval",
            category=NodeCategory.HUMAN_IN_THE_LOOP,
            description="Pauses workflow execution and requests manual sign-off or review from a human via Slack, email, or web UI.",
            inputs=[
                PortDefinition(id="in_summary", name="Review Context", port_type=PortType.INPUT, data_type=PortDataType.OBJECT, description="Summary details and request payload for the reviewer"),
            ],
            outputs=[
                PortDefinition(id="out_approved", name="Approved", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Proceeds when approved by reviewer"),
                PortDefinition(id="out_rejected", name="Rejected", port_type=PortType.OUTPUT, data_type=PortDataType.OBJECT, description="Proceeds when rejected with reviewer notes"),
            ],
            default_config={"timeout_hours": 24, "channel": "slack", "approver_role": "manager"},
            compatible_tools=[
                ToolDefinition(name="Slack", operation="send_approval_card", description="Interactive button card in Slack"),
                ToolDefinition(name="Email", operation="send_approval_link", description="Email with one-click approve/reject link"),
            ],
            icon="user-check",
            tags=["human", "approval", "review", "signoff", "manager"],
        )
    )

    return registry


@lru_cache(maxsize=1)
def get_default_registry() -> NodeRegistry:
    """Return the cached singleton instance of the standard NodeRegistry."""
    return _create_standard_registry()
