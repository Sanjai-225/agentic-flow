"""Persistence for executions. Each call uses a short-lived session so SQLite locks stay brief."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AiUsageRecord, Execution, ExecutionLog, NodeExecution, WorkflowVersion
from app.engine.contracts import LogEntry
from app.engine.redaction import storable


def utcnow() -> datetime:
    return datetime.now(UTC)


class ExecutionStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def load(self, execution_id: str) -> Tuple[Optional[Execution], Optional[Dict[str, Any]]]:
        async with self._sm() as session:
            execution = await session.get(Execution, execution_id)
            if execution is None:
                return None, None
            row = await session.execute(
                select(WorkflowVersion.definition).where(
                    WorkflowVersion.workflow_id == execution.workflow_id,
                    WorkflowVersion.version == execution.workflow_version,
                )
            )
            return execution, row.scalar_one_or_none()

    async def update_execution(self, execution_id: str, **fields: Any) -> None:
        for key in ("input", "output", "error"):
            if key in fields and fields[key] is not None:
                fields[key] = storable(fields[key])
        async with self._sm() as session:
            await session.execute(update(Execution).where(Execution.id == execution_id).values(**fields))
            await session.commit()

    async def init_nodes(self, execution_id: str, nodes: Iterable[Tuple[str, str, str, int]]) -> None:
        async with self._sm() as session:
            for node_id, operation, label, position in nodes:
                session.add(NodeExecution(execution_id=execution_id, node_id=node_id, operation=operation,
                                          label=label, position=position, status="pending"))
            await session.commit()

    async def update_node(self, execution_id: str, node_id: str, **fields: Any) -> None:
        for key in ("inputs", "output", "error", "node_metadata", "route"):
            if key in fields and fields[key] is not None:
                fields[key] = storable(fields[key])
        async with self._sm() as session:
            await session.execute(
                update(NodeExecution)
                .where(NodeExecution.execution_id == execution_id, NodeExecution.node_id == node_id)
                .values(**fields)
            )
            await session.commit()

    async def skip_pending_nodes(self, execution_id: str, reason: str) -> None:
        async with self._sm() as session:
            await session.execute(
                update(NodeExecution)
                .where(NodeExecution.execution_id == execution_id, NodeExecution.status.in_(["pending", "running"]))
                .values(status="skipped", node_metadata={"skip_reason": reason}, finished_at=utcnow())
            )
            await session.commit()

    async def add_logs(self, execution_id: str, entries: List[LogEntry]) -> None:
        if not entries:
            return
        async with self._sm() as session:
            for e in entries:
                session.add(ExecutionLog(execution_id=execution_id, node_id=e.node_id, level=e.level,
                                         message=e.message[:4000], data=storable(e.data) if e.data else None,
                                         ts=e.ts))
            await session.commit()

    async def add_ai_usage(self, execution_id: str, user_id: str, workflow_id: str, node_id: str,
                           record: Dict[str, Any]) -> None:
        """Persist one model call's provider-reported usage, tied to the execution, node and user."""
        allowed = {"operation", "provider", "model", "credential_source", "status", "error_category",
                   "fallback_used", "input_tokens", "output_tokens", "total_tokens", "duration_ms"}
        async with self._sm() as session:
            session.add(AiUsageRecord(execution_id=execution_id, user_id=user_id, workflow_id=workflow_id,
                                      node_id=node_id, **{k: v for k, v in record.items() if k in allowed}))
            await session.commit()
