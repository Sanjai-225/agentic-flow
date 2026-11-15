"""Typed contracts shared by the execution engine and node executors.

Every executor implements::

    async def execute(config, inputs, ctx) -> NodeExecutionResult

``config`` is a validated instance of the node definition's config model with
expressions already resolved (except lazy fields), ``inputs`` are the node's
resolved named input mappings and ``ctx`` carries run metadata and secure
service access. Secrets never travel through config, inputs or state.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Awaitable, Callable, ClassVar, Dict, List, Mapping, Optional, Protocol, Set, Type

from pydantic import BaseModel, Field

from app.core.errors import NodeError


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"  # reserved for approval/wait interruptions (Milestone 4)
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"  # reserved for approval/wait interruptions (Milestone 4)


class NodeExecutionResult(BaseModel):
    """Standard result returned by every executor."""

    status: NodeStatus = NodeStatus.SUCCESS
    output: Any = None
    error: Optional[NodeError] = None
    route: Optional[List[str]] = Field(
        default=None, description="Output ports to follow. None means the default 'main' port."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CredentialAccessor(Protocol):
    async def get(self, credential_id: str, expected_types: Optional[List[str]] = None,
                  field: str = "auth.credential_id") -> Dict[str, Any]:
        """Return decrypted credential data owned by the executing user, or raise NodeExecutionError."""
        ...


@dataclass
class LogEntry:
    level: str
    message: str
    data: Optional[Dict[str, Any]] = None
    node_id: Optional[str] = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


class ExecutionLogger:
    """Collects structured log entries; the runner persists them."""

    def __init__(self, node_id: Optional[str] = None) -> None:
        self.node_id = node_id
        self.entries: List[LogEntry] = []

    def _add(self, level: str, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self.entries.append(LogEntry(level=level, message=message, data=data, node_id=self.node_id))

    def debug(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add("debug", message, data)

    def info(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add("info", message, data)

    def warning(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add("warning", message, data)

    def error(self, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._add("error", message, data)


@dataclass
class ExecutionContext:
    """Per-node execution context handed to executors."""

    workflow_id: str
    workflow_version: int
    execution_id: str
    node_id: str
    operation: str
    user_id: str
    correlation_id: str
    upstream: Any
    state: Mapping[str, Any]
    credentials: CredentialAccessor
    logger: ExecutionLogger
    cancel_event: asyncio.Event
    timeout_seconds: float
    attempt: int = 1
    resolve: Optional[Callable[[Any, str, Optional[Dict[str, Any]]], Any]] = None
    settings: Any = None
    # Async callback persisting one AI usage record (provider, model, tokens, ...) for this node; None in
    # unit tests. Records are always associated with this execution, node and user by the runner.
    usage_sink: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    # Secret values resolved while running this node (e.g. provider API keys). The runner scrubs them from the
    # recorded output, metadata, logs and errors. Executors add every secret they decrypt.
    secrets: Set[str] = field(default_factory=set)
    # Active incoming connections grouped by target port ({port: [{"source": node_id, "output": ...}]}).
    inputs_by_port: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()


class NodeExecutor(ABC):
    """Base class for node executors. Subclasses are stateless."""

    operation_id: ClassVar[str]
    config_model: ClassVar[Type[BaseModel]]

    @abstractmethod
    async def execute(
        self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> NodeExecutionResult:
        ...

    def has_side_effects(self, config: BaseModel, default: bool) -> bool:
        """Whether this particular configuration changes external state."""
        return default
