"""Database-driven scheduler for Schedule Trigger workflows.

Not an in-memory timer: every schedule (spec, time zone, next/last run, last status) lives in
``workflow_schedules``. A lightweight asyncio loop polls for due schedules every
``SCHEDULER_POLL_SECONDS`` and, for each one:

1. checks the owning workflow is active and the schedule enabled;
2. applies the misfire policy if the occurrence is overdue (e.g. after downtime): ``skip`` drops missed
   occurrences, ``run_once`` runs a single catch-up - a backlog is never replayed;
3. *claims* the occurrence by inserting ``schedule_occurrences(schedule_id, scheduled_for)``. The unique
   constraint makes duplicate runs impossible, even with several workers/processes polling the same DB;
4. re-plans the current workflow version for its owner, creates an execution with ``trigger_type=schedule``
   and schedule metadata as the trigger payload, and starts it through the normal engine;
5. advances ``next_run_at`` (stable phase for interval schedules) and records last run/status.

Restarts: rows persist, so a restarted process simply resumes polling; overdue rows go through step 2.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import Execution, ScheduleOccurrence, Workflow, WorkflowSchedule
from app.schemas.workflow import WorkflowSchema
from app.services import workflow_store as store
from app.services.schedules import next_runs, schedule_problems

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class Scheduler:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], manager: Any,
                 settings: Optional[Settings] = None) -> None:
        self._sm = sessionmaker
        self._manager = manager
        self._settings = settings or get_settings()
        self._task: Optional[asyncio.Task[None]] = None
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------ lifecycle
    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._loop(), name="schedule-loop")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _loop(self) -> None:
        await self.reconcile()
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception:  # never let one bad row stop scheduling
                logger.exception("Scheduler tick failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._settings.SCHEDULER_POLL_SECONDS)
            except TimeoutError:
                pass

    # ------------------------------------------------------------------ work
    async def reconcile(self) -> int:
        """On startup: give every enabled schedule without a next run one (no backlog is created)."""
        now = utcnow()
        fixed = 0
        async with self._sm() as session:
            rows = (await session.execute(select(WorkflowSchedule).where(WorkflowSchedule.enabled.is_(True),
                                                                         WorkflowSchedule.next_run_at.is_(None))))
            for row in rows.scalars():
                if not schedule_problems(row.spec):
                    row.next_run_at = next_runs(row.spec, now, anchor=now)[0]
                    fixed += 1
            await session.commit()
        return fixed

    def _grace(self) -> timedelta:
        return timedelta(seconds=max(60.0, 3 * float(self._settings.SCHEDULER_POLL_SECONDS)))

    async def tick(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Fire every due schedule once. Returns a report of what happened (used by tests and logs)."""
        now = now or utcnow()
        report: List[Dict[str, Any]] = []
        async with self._sm() as session:
            due = (await session.execute(
                select(WorkflowSchedule.id).join(Workflow, Workflow.id == WorkflowSchedule.workflow_id)
                .where(WorkflowSchedule.enabled.is_(True), Workflow.active.is_(True),
                       WorkflowSchedule.next_run_at.is_not(None), WorkflowSchedule.next_run_at <= now)
                .order_by(WorkflowSchedule.next_run_at)
            )).scalars().all()
        for schedule_id in due:
            report.append(await self._fire(schedule_id, now))
        return report

    async def _fire(self, schedule_id: str, now: datetime) -> Dict[str, Any]:
        async with self._sm() as session:
            schedule = await session.get(WorkflowSchedule, schedule_id)
            if schedule is None or schedule.next_run_at is None:
                return {"schedule_id": schedule_id, "result": "gone"}
            occurrence = _aware(schedule.next_run_at)
            assert occurrence is not None
            spec, policy = schedule.spec, (schedule.spec or {}).get("misfire_policy", "skip")
            following = next_runs(spec, max(now, occurrence), anchor=occurrence)[0]

            if now - occurrence > self._grace() and policy == "skip":
                schedule.next_run_at = following
                schedule.last_status = "missed"
                schedule.last_error = f"Occurrence {occurrence.isoformat()} was missed (server not running); " \
                                      "skipped per misfire policy."
                await session.commit()
                logger.info("Schedule %s: skipped missed occurrence %s", schedule_id, occurrence)
                return {"schedule_id": schedule_id, "result": "skipped_missed", "scheduled_for": occurrence}

            # Claim the occurrence. A second worker hitting the same occurrence loses here.
            claim = ScheduleOccurrence(schedule_id=schedule.id, scheduled_for=occurrence)
            session.add(claim)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                return {"schedule_id": schedule_id, "result": "duplicate", "scheduled_for": occurrence}

            schedule.next_run_at = following
            schedule.last_run_at = now
            record = await session.get(Workflow, schedule.workflow_id)
            definition = await store.get_version_definition(session, record.id, record.current_version) \
                if record else None
            if record is None or definition is None:
                schedule.last_status, schedule.last_error = "failed", "The workflow no longer exists."
                await session.commit()
                return {"schedule_id": schedule_id, "result": "failed"}
            workflow = WorkflowSchema.model_validate(definition)
            if schedule.node_id not in {n.id for n in workflow.nodes}:
                schedule.enabled, schedule.last_status = False, "failed"
                schedule.last_error = "The Schedule Trigger node was removed from the workflow."
                await session.commit()
                return {"schedule_id": schedule_id, "result": "failed"}
            plan = await store.plan_for_user(session, record.user_id, workflow)
            if not plan.valid:
                schedule.last_status = "invalid"
                schedule.last_error = f"Workflow failed validation: {plan.errors[0].message}"
                await session.commit()
                return {"schedule_id": schedule_id, "result": "invalid"}
            payload = {"schedule_id": schedule.id, "scheduled_for": occurrence.isoformat(),
                       "fired_at": now.isoformat(), "timezone": schedule.timezone, "workflow_id": record.id,
                       "catch_up": now - occurrence > self._grace()}
            execution = Execution(workflow_id=record.id, workflow_version=record.current_version,
                                  user_id=record.user_id, status="pending", trigger_type="schedule", input=payload,
                                  correlation_id=claim.schedule_id + ":" + occurrence.strftime("%Y%m%dT%H%M%SZ"))
            session.add(execution)
            await session.flush()
            claim.execution_id = execution.id
            schedule.last_execution_id = execution.id
            schedule.last_status, schedule.last_error = "started", None
            await session.commit()
            execution_id = execution.id
        self._manager.start(execution_id)
        logger.info("Schedule %s fired for %s -> execution %s", schedule_id, occurrence, execution_id)
        return {"schedule_id": schedule_id, "result": "started", "execution_id": execution_id,
                "scheduled_for": occurrence}
