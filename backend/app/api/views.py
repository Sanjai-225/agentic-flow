"""Converters from ORM rows to API response models."""

from datetime import datetime, UTC
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Execution
from app.schemas.api import ExecutionDetail, ExecutionLogOut, ExecutionSummary, NodeExecutionOut
from app.services import workflow_store as store


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _duration(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if not start or not end:
        return None
    return round((_utc(end) - _utc(start)).total_seconds() * 1000, 2)  # type: ignore[operator]


def execution_summary(e: Execution) -> ExecutionSummary:
    return ExecutionSummary(
        id=e.id, workflow_id=e.workflow_id, workflow_version=e.workflow_version, status=e.status,
        trigger_type=e.trigger_type, created_at=_utc(e.created_at), started_at=_utc(e.started_at),
        finished_at=_utc(e.finished_at), duration_ms=_duration(e.started_at, e.finished_at), error=e.error,
    )


async def execution_detail(session: AsyncSession, e: Execution, include_definition: bool = True) -> ExecutionDetail:
    nodes, logs = await store.execution_children(session, e.id)
    definition = await store.get_version_definition(session, e.workflow_id, e.workflow_version) \
        if include_definition else None
    summary = execution_summary(e)
    return ExecutionDetail(
        **summary.model_dump(), correlation_id=e.correlation_id, input=e.input, output=e.output,
        nodes=[NodeExecutionOut(
            node_id=n.node_id, operation=n.operation, label=n.label, position=n.position, status=n.status,
            attempts=n.attempts, inputs=n.inputs, output=n.output, error=n.error, route=n.route,
            metadata=n.node_metadata, started_at=_utc(n.started_at), finished_at=_utc(n.finished_at),
            duration_ms=n.duration_ms,
        ) for n in nodes],
        logs=[ExecutionLogOut(node_id=log.node_id, level=log.level, message=log.message, data=log.data,
                              ts=_utc(log.ts)) for log in logs],  # type: ignore[arg-type]
        workflow_definition=definition,
    )
