"""User-scoped persistence for workflows, versions and execution records."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Execution, ExecutionLog, NodeExecution, Workflow, WorkflowVersion, new_id
from app.engine.contracts import WorkflowStatus
from app.engine.planner import ExecutionPlan, plan_workflow
from app.schemas.workflow import WorkflowSchema
from app.services.credentials import credential_ids_for_user
from app.services.workflow_upgrade import upgrade_workflow


class DefinitionError(ValueError):
    def __init__(self, errors: List[Dict[str, str]]) -> None:
        super().__init__("Invalid workflow definition.")
        self.errors = errors


def parse_definition(raw: Dict[str, Any], workflow_id: Optional[str] = None) -> WorkflowSchema:
    """Validate (v1 or v2) JSON and return an upgraded canonical v2 workflow."""
    data = dict(raw)
    if workflow_id:
        data["workflow_id"] = workflow_id
    data.setdefault("workflow_id", f"draft-{uuid.uuid4().hex[:8]}")
    if not data.get("workflow_name"):
        data["workflow_name"] = data.get("name") or "Untitled workflow"
    data.pop("name", None)
    try:
        workflow = WorkflowSchema.model_validate(data)
    except ValidationError as exc:
        raise DefinitionError([
            {"field": ".".join(str(p) for p in err["loc"]) or "definition", "message": err["msg"]}
            for err in exc.errors()
        ]) from exc
    return upgrade_workflow(workflow)


async def sync_triggers(session: AsyncSession, record: Workflow, workflow: WorkflowSchema) -> None:
    """Persist public form endpoints and schedules for the saved version (same transaction as the save)."""
    from app.services.forms import sync_forms
    from app.services.schedules import sync_schedules

    await sync_forms(session, record, workflow)
    await sync_schedules(session, record, workflow)


async def plan_for_user(session: AsyncSession, user_id: str, workflow: WorkflowSchema) -> ExecutionPlan:
    return plan_workflow(workflow, credential_ids=await credential_ids_for_user(session, user_id))


async def get_owned_workflow(session: AsyncSession, user_id: str, workflow_id: str) -> Optional[Workflow]:
    row = await session.execute(select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id))
    return row.scalar_one_or_none()


async def get_version_definition(session: AsyncSession, workflow_id: str, version: int) -> Optional[Dict[str, Any]]:
    row = await session.execute(
        select(WorkflowVersion.definition).where(WorkflowVersion.workflow_id == workflow_id,
                                                 WorkflowVersion.version == version)
    )
    return row.scalar_one_or_none()


async def create_workflow(session: AsyncSession, user_id: str, raw: Dict[str, Any]) -> Tuple[Workflow, WorkflowSchema]:
    wf_id = new_id("wf")
    workflow = parse_definition(raw, workflow_id=wf_id)
    workflow.version = 1
    record = Workflow(id=wf_id, user_id=user_id, name=workflow.workflow_name, description=workflow.description,
                      current_version=1)
    session.add(record)
    session.add(WorkflowVersion(workflow_id=wf_id, version=1, definition=workflow.model_dump(mode="json")))
    await session.flush()
    await sync_triggers(session, record, workflow)
    await session.commit()
    await session.refresh(record)
    return record, workflow


async def save_new_version(session: AsyncSession, record: Workflow, raw: Dict[str, Any]) -> WorkflowSchema:
    workflow = parse_definition(raw, workflow_id=record.id)
    next_version = record.current_version + 1
    workflow.version = next_version
    record.current_version = next_version
    record.name = workflow.workflow_name
    record.description = workflow.description
    session.add(WorkflowVersion(workflow_id=record.id, version=next_version, definition=workflow.model_dump(mode="json")))
    await sync_triggers(session, record, workflow)
    await session.commit()
    await session.refresh(record)
    return workflow


async def last_status_by_workflow(session: AsyncSession, user_id: str) -> Dict[str, str]:
    latest = (
        select(Execution.workflow_id, func.max(Execution.created_at).label("latest"))
        .where(Execution.user_id == user_id)
        .group_by(Execution.workflow_id)
        .subquery()
    )
    rows = await session.execute(
        select(Execution.workflow_id, Execution.status).join(
            latest, (Execution.workflow_id == latest.c.workflow_id) & (Execution.created_at == latest.c.latest)
        )
    )
    return {wf: st for wf, st in rows.all()}


async def create_execution(session: AsyncSession, record: Workflow, trigger_type: str, payload: Any) -> Execution:
    execution = Execution(
        workflow_id=record.id, workflow_version=record.current_version, user_id=record.user_id,
        status=WorkflowStatus.PENDING.value, trigger_type=trigger_type, input=payload,
        correlation_id=uuid.uuid4().hex,
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)
    return execution


async def get_owned_execution(session: AsyncSession, user_id: str, execution_id: str) -> Optional[Execution]:
    row = await session.execute(select(Execution).where(Execution.id == execution_id, Execution.user_id == user_id))
    return row.scalar_one_or_none()


async def execution_children(session: AsyncSession, execution_id: str) -> Tuple[List[NodeExecution], List[ExecutionLog]]:
    nodes = await session.execute(
        select(NodeExecution).where(NodeExecution.execution_id == execution_id).order_by(NodeExecution.position)
    )
    logs = await session.execute(
        select(ExecutionLog).where(ExecutionLog.execution_id == execution_id).order_by(ExecutionLog.id)
    )
    return list(nodes.scalars()), list(logs.scalars())
