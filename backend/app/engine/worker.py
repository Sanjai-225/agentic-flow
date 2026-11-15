"""In-process asyncio execution manager.

Executions run as background tasks inside the API process. All state is
persisted by the runner, so a restart never loses history: on startup,
runs that were still ``pending``/``running`` are marked failed
("interrupted by restart"). Resuming them is Milestone 4 scope.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, UTC
from typing import Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import ErrorCategory, NodeError
from app.db.models import Execution, NodeExecution
from app.engine.contracts import WorkflowStatus
from app.engine.runner import WorkflowRunner

logger = logging.getLogger(__name__)


class ExecutionManager:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], runner: Optional[WorkflowRunner] = None) -> None:
        self._sm = sessionmaker
        self._runner = runner or WorkflowRunner(sessionmaker)
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._cancel: Dict[str, asyncio.Event] = {}

    def start(self, execution_id: str) -> asyncio.Task[None]:
        event = asyncio.Event()
        self._cancel[execution_id] = event
        task = asyncio.create_task(self._runner.run(execution_id, event), name=f"execution:{execution_id}")
        self._tasks[execution_id] = task
        task.add_done_callback(lambda _t: self._cleanup(execution_id))
        return task

    def _cleanup(self, execution_id: str) -> None:
        self._tasks.pop(execution_id, None)
        self._cancel.pop(execution_id, None)

    async def run_and_wait(self, execution_id: str, timeout: float) -> bool:
        """Start and wait up to ``timeout`` seconds. Returns True if the run finished."""
        task = self.start(execution_id)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def is_active(self, execution_id: str) -> bool:
        return execution_id in self._tasks

    async def cancel(self, execution_id: str) -> bool:
        """Request cancellation. Returns False if the execution is not running in this process."""
        event = self._cancel.get(execution_id)
        if event is None:
            return False
        event.set()
        return True

    async def reconcile_interrupted(self) -> int:
        """Mark executions left pending/running by a previous process as failed."""
        now = datetime.now(UTC)
        error = NodeError(
            category=ErrorCategory.ENGINE_ERROR,
            message="Execution was interrupted by a server restart before it finished.",
            suggestion="Re-run the workflow. Automatic resume is not supported yet.",
        ).model_dump(mode="json")
        async with self._sm() as session:
            rows = await session.execute(
                select(Execution.id).where(Execution.status.in_([WorkflowStatus.PENDING.value,
                                                                  WorkflowStatus.RUNNING.value]))
            )
            ids = [i for i in rows.scalars() if i not in self._tasks]
            if not ids:
                return 0
            await session.execute(update(Execution).where(Execution.id.in_(ids))
                                  .values(status=WorkflowStatus.FAILED.value, error=error, finished_at=now))
            await session.execute(update(NodeExecution)
                                  .where(NodeExecution.execution_id.in_(ids), NodeExecution.status == "running")
                                  .values(status="failed", error=error, finished_at=now))
            await session.execute(update(NodeExecution)
                                  .where(NodeExecution.execution_id.in_(ids), NodeExecution.status == "pending")
                                  .values(status="skipped", finished_at=now,
                                          node_metadata={"skip_reason": "interrupted by restart"}))
            await session.commit()
        logger.warning("Marked %d interrupted execution(s) as failed", len(ids))
        return len(ids)

    async def shutdown(self, timeout: float = 5.0) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
