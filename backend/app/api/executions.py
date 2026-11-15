"""Execution inspection and cancellation."""

from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_manager
from app.api.views import execution_detail
from app.core.errors import ErrorCategory, NodeError
from app.db.models import NodeExecution, User
from app.db.session import get_session
from app.engine.contracts import WorkflowStatus
from app.engine.worker import ExecutionManager
from app.schemas.api import ExecutionDetail
from app.services import workflow_store as store

router = APIRouter(prefix="/api/executions", tags=["Executions"])


@router.get("/{execution_id}", response_model=ExecutionDetail)
async def get_execution(execution_id: str, include_definition: bool = Query(True),
                        user: User = Depends(get_current_user),
                        session: AsyncSession = Depends(get_session)) -> ExecutionDetail:
    execution = await store.get_owned_execution(session, user.id, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    return await execution_detail(session, execution, include_definition)


@router.post("/{execution_id}/cancel")
async def cancel_execution(execution_id: str, user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session),
                           manager: ExecutionManager = Depends(get_manager)) -> dict:
    execution = await store.get_owned_execution(session, user.id, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    if WorkflowStatus(execution.status).is_terminal:
        raise HTTPException(status_code=409, detail=f"Execution already {execution.status}.")
    if await manager.cancel(execution_id):
        # The runner observes the signal, stops at the next safe point and persists 'cancelled'.
        return {"execution_id": execution_id, "status": "cancelling"}

    # Not active in this process (never started): cancel the record directly.
    now = datetime.now(UTC)
    execution.status = WorkflowStatus.CANCELLED.value
    execution.finished_at = now
    execution.error = NodeError(category=ErrorCategory.CANCELLED,
                                message="Execution was cancelled.").with_defaults().model_dump(mode="json")
    await session.execute(
        update(NodeExecution)
        .where(NodeExecution.execution_id == execution_id, NodeExecution.status.in_(["pending", "running"]))
        .values(status="skipped", finished_at=now, node_metadata={"skip_reason": "execution cancelled"})
    )
    await session.commit()
    return {"execution_id": execution_id, "status": "cancelled"}
