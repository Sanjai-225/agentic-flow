"""Shared error taxonomy for validation and workflow execution.

Every failure surfaced to a user carries a category, a human-readable message,
redacted technical detail, retryability and a suggested corrective action.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ErrorCategory(str, Enum):
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    GRAPH_VALIDATION = "GRAPH_VALIDATION"
    UNSUPPORTED_CAPABILITY = "UNSUPPORTED_CAPABILITY"
    MISSING_INPUT = "MISSING_INPUT"
    INVALID_MAPPING = "INVALID_MAPPING"
    MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
    AUTH_FAILURE = "AUTH_FAILURE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MODEL_ERROR = "MODEL_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    NODE_EXECUTION = "NODE_EXECUTION"
    ENGINE_ERROR = "ENGINE_ERROR"
    CANCELLED = "CANCELLED"
    # --- AI model / agent (Milestone 2). Model errors, tool errors and permission errors stay distinct. ---
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"        # provider down, network, 5xx, overloaded
    MODEL_AUTH = "MODEL_AUTH"                      # provider rejected the API key / permissions
    MODEL_TIMEOUT = "MODEL_TIMEOUT"                # inference did not finish in time
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"        # provider/model/feature not in the verified catalogue
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"  # empty/refused/unparseable model response
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"  # output failed the JSON schema after repair
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"          # unknown or unauthorized tool requested
    TOOL_ARGS_INVALID = "TOOL_ARGS_INVALID"        # tool arguments failed validation
    TOOL_FAILED = "TOOL_FAILED"                    # tool raised while executing
    TOOL_TIMEOUT = "TOOL_TIMEOUT"                  # tool exceeded its timeout
    ITERATION_LIMIT = "ITERATION_LIMIT"            # agent iteration / tool-call limit reached
    USAGE_LIMIT = "USAGE_LIMIT"                    # token budget / input or output size limit


DEFAULT_SUGGESTIONS: Dict[ErrorCategory, str] = {
    ErrorCategory.SCHEMA_VALIDATION: "Fix the highlighted configuration field so it matches the expected type.",
    ErrorCategory.GRAPH_VALIDATION: "Check the workflow connections: every node must be reachable from the trigger.",
    ErrorCategory.UNSUPPORTED_CAPABILITY: "Replace this node with an executable node from the node library, or remove it.",
    ErrorCategory.MISSING_INPUT: "Check that the upstream node produces the referenced field, or add a default value.",
    ErrorCategory.INVALID_MAPPING: "Reference only nodes that run before this node on the same path, e.g. {{nodes.<id>.output.<field>}}.",
    ErrorCategory.MISSING_CREDENTIALS: "Select or create the required credential in the node configuration.",
    ErrorCategory.AUTH_FAILURE: "Verify the credential is valid and has not expired.",
    ErrorCategory.PERMISSION_DENIED: "The current user is not allowed to use this resource.",
    ErrorCategory.PROVIDER_ERROR: "The external service returned an error. Inspect the response details and the request configuration.",
    ErrorCategory.MODEL_ERROR: "The model returned an invalid response. Adjust the prompt or output schema.",
    ErrorCategory.TIMEOUT: "Increase the node timeout or check that the external service is responsive.",
    ErrorCategory.RATE_LIMIT: "The service is rate limiting requests. Retry later or reduce request volume.",
    ErrorCategory.NODE_EXECUTION: "Inspect the node input and configuration.",
    ErrorCategory.ENGINE_ERROR: "An internal engine error occurred. Re-run the workflow; report it if it persists.",
    ErrorCategory.CANCELLED: "The execution was cancelled by a user.",
    ErrorCategory.MODEL_UNAVAILABLE: "The model provider is unavailable. Retry later or configure a fallback model.",
    ErrorCategory.MODEL_AUTH: "Check the provider API key in the selected credential (or the platform key) and its permissions.",
    ErrorCategory.MODEL_TIMEOUT: "Increase the inference timeout, shorten the prompt, or try a faster model.",
    ErrorCategory.UNSUPPORTED_MODEL: "Choose a provider and model from the supported model list.",
    ErrorCategory.INVALID_MODEL_OUTPUT: "Adjust the instructions or prompt; check the raw model response in the execution trace.",
    ErrorCategory.STRUCTURED_OUTPUT_INVALID: "Simplify the output schema or make the instructions describe each field more clearly.",
    ErrorCategory.TOOL_NOT_ALLOWED: "Enable the tool in the agent's tool list, or adjust the instructions so the agent does not need it.",
    ErrorCategory.TOOL_ARGS_INVALID: "The model sent arguments that do not match the tool's schema; clarify the instructions.",
    ErrorCategory.TOOL_FAILED: "Inspect the tool call in the agent trace; check the tool input and any external service it calls.",
    ErrorCategory.TOOL_TIMEOUT: "Increase the per-tool timeout or make the task smaller.",
    ErrorCategory.ITERATION_LIMIT: "Raise the iteration/tool-call limit or simplify the task.",
    ErrorCategory.USAGE_LIMIT: "Raise the token or size limit, or reduce the input size.",
}


class NodeError(BaseModel):
    """Structured, user-facing error attached to a node or execution."""

    category: ErrorCategory
    message: str = Field(..., description="Human-readable explanation.")
    technical_detail: Optional[str] = Field(default=None, description="Redacted technical detail.")
    retryable: bool = False
    field: Optional[str] = Field(default=None, description="Offending config/input path, when identifiable.")
    suggestion: Optional[str] = None
    node_id: Optional[str] = None
    operation: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    def with_defaults(self) -> NodeError:
        if not self.suggestion:
            self.suggestion = DEFAULT_SUGGESTIONS.get(self.category)
        return self


class NodeExecutionError(Exception):
    """Raised by executors/resolvers to fail a node with a structured error."""

    def __init__(
        self,
        category: ErrorCategory,
        message: str,
        *,
        retryable: bool = False,
        field: Optional[str] = None,
        suggestion: Optional[str] = None,
        technical_detail: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error = NodeError(
            category=category,
            message=message,
            retryable=retryable,
            field=field,
            suggestion=suggestion,
            technical_detail=technical_detail,
            details=details or {},
        ).with_defaults()


class ValidationIssue(BaseModel):
    """A single pre-execution validation problem."""

    category: ErrorCategory
    message: str
    severity: str = Field(default="error", description="'error' blocks execution; 'warning' does not.")
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    field: Optional[str] = None
    suggestion: Optional[str] = None

    def with_defaults(self) -> ValidationIssue:
        if not self.suggestion:
            self.suggestion = DEFAULT_SUGGESTIONS.get(self.category)
        return self
