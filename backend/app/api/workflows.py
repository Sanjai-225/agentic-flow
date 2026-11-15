"""Workflow CRUD, validation, execution start and webhook-token management."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_manager
from app.api.views import execution_detail, execution_summary
from app.core.config import get_settings
from app.core.security import generate_token, hash_token
from app.db.models import Execution, User, Workflow, WorkflowForm, WorkflowSchedule
from app.db.session import get_session
from app.engine.output_fields import infer_output_fields
from app.engine.worker import ExecutionManager
from app.schemas.api import (
    ExecutionSummary,
    FormInfo,
    RunWorkflowRequest,
    SaveWorkflowRequest,
    ScheduleInfo,
    SchedulePreviewRequest,
    ValidateWorkflowRequest,
    WebhookInfo,
    WorkflowActiveUpdate,
    WorkflowRecord,
    WorkflowSummary,
)
from app.schemas.workflow import WorkflowSchema
from app.services import workflow_store as store

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


def _definition_error(exc: store.DefinitionError) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": "Invalid workflow definition.", "errors": exc.errors})


async def _record(session: AsyncSession, record: Workflow, user: User,
                  workflow: Optional[WorkflowSchema] = None) -> WorkflowRecord:
    if workflow is None:
        definition = await store.get_version_definition(session, record.id, record.current_version)
        workflow = WorkflowSchema.model_validate(definition)
    plan = await store.plan_for_user(session, user.id, workflow)
    return WorkflowRecord(
        id=record.id, name=record.name, description=record.description, version=record.current_version,
        has_webhook=bool(record.webhook_token_hash), active=bool(record.active), created_at=record.created_at,
        updated_at=record.updated_at,
        definition=workflow.model_dump(mode="json"), validation=plan.to_dict(),
    )


async def _owned(session: AsyncSession, user: User, workflow_id: str) -> Workflow:
    record = await store.get_owned_workflow(session, user.id, workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return record


@router.get("", response_model=List[WorkflowSummary])
async def list_workflows(user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session)) -> List[WorkflowSummary]:
    rows = await session.execute(select(Workflow).where(Workflow.user_id == user.id).order_by(Workflow.updated_at.desc()))
    last = await store.last_status_by_workflow(session, user.id)
    return [
        WorkflowSummary(id=w.id, name=w.name, description=w.description, version=w.current_version,
                        has_webhook=bool(w.webhook_token_hash), active=bool(w.active), created_at=w.created_at,
                        updated_at=w.updated_at, last_execution_status=last.get(w.id))
        for w in rows.scalars()
    ]


@router.post("", response_model=WorkflowRecord, status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: SaveWorkflowRequest, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)) -> WorkflowRecord:
    try:
        record, workflow = await store.create_workflow(session, user.id, payload.definition)
    except store.DefinitionError as exc:
        raise _definition_error(exc) from exc
    return await _record(session, record, user, workflow)


@router.post("/validate")
async def validate_unsaved(payload: ValidateWorkflowRequest, user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session)) -> Dict[str, Any]:
    """Validate a definition without saving it (used by the editor)."""
    try:
        workflow = store.parse_definition(payload.definition)
    except store.DefinitionError as exc:
        return {"valid": False, "issues": [
            {"category": "SCHEMA_VALIDATION", "severity": "error", "message": f"{e['field']}: {e['message']}",
             "field": e["field"], "node_id": None, "edge_id": None, "suggestion": None} for e in exc.errors
        ], "order": [], "trigger_node_id": None}
    return (await store.plan_for_user(session, user.id, workflow)).to_dict()


@router.post("/output-fields")
async def output_fields(payload: ValidateWorkflowRequest, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Data fields each node is expected to produce, inferred from config/registry (nothing is executed).

    Lets the editor's data picker offer references before the workflow has run.
    """
    try:
        workflow = store.parse_definition(payload.definition)
    except store.DefinitionError as exc:
        raise _definition_error(exc) from exc
    return {"nodes": infer_output_fields(workflow)}


@router.get("/{workflow_id}", response_model=WorkflowRecord)
async def get_workflow(workflow_id: str, user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_session)) -> WorkflowRecord:
    return await _record(session, await _owned(session, user, workflow_id), user)


@router.put("/{workflow_id}", response_model=WorkflowRecord)
async def update_workflow(workflow_id: str, payload: SaveWorkflowRequest, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)) -> WorkflowRecord:
    record = await _owned(session, user, workflow_id)
    try:
        workflow = await store.save_new_version(session, record, payload.definition)
    except store.DefinitionError as exc:
        raise _definition_error(exc) from exc
    return await _record(session, record, user, workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)) -> Response:
    record = await _owned(session, user, workflow_id)
    await session.delete(record)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/validate")
async def validate_saved(workflow_id: str, user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session)) -> Dict[str, Any]:
    record = await _owned(session, user, workflow_id)
    definition = await store.get_version_definition(session, record.id, record.current_version)
    return (await store.plan_for_user(session, user.id, WorkflowSchema.model_validate(definition))).to_dict()


@router.post("/{workflow_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_workflow(
    workflow_id: str,
    payload: RunWorkflowRequest,
    response: Response,
    wait: bool = Query(False, description="Wait for the run to finish (bounded by the max execution duration)."),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    manager: ExecutionManager = Depends(get_manager),
) -> Dict[str, Any]:
    record = await _owned(session, user, workflow_id)
    definition = await store.get_version_definition(session, record.id, record.current_version)
    plan = await store.plan_for_user(session, user.id, WorkflowSchema.model_validate(definition))
    if not plan.valid:
        raise HTTPException(status_code=422, detail={
            "message": "Workflow cannot run until these problems are fixed.",
            "issues": [i.model_dump(mode="json") for i in plan.errors],
        })
    execution = await store.create_execution(session, record, "manual", payload.input)
    if wait:
        finished = await manager.run_and_wait(execution.id, timeout=get_settings().EXECUTION_MAX_DURATION_SECONDS)
        await session.refresh(execution)
        if finished:
            response.status_code = status.HTTP_200_OK
        detail = await execution_detail(session, execution)
        return detail.model_dump(mode="json")
    manager.start(execution.id)
    return {"execution_id": execution.id, "status": execution.status, "workflow_version": execution.workflow_version}


@router.get("/{workflow_id}/executions", response_model=List[ExecutionSummary])
async def list_executions(workflow_id: str, limit: int = Query(50, ge=1, le=200),
                          user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)) -> List[ExecutionSummary]:
    await _owned(session, user, workflow_id)
    rows = await session.execute(
        select(Execution).where(Execution.workflow_id == workflow_id, Execution.user_id == user.id)
        .order_by(Execution.created_at.desc()).limit(limit)
    )
    return [execution_summary(e) for e in rows.scalars()]


@router.post("/{workflow_id}/webhook", response_model=WebhookInfo)
async def create_webhook_token(workflow_id: str, user: User = Depends(get_current_user),
                               session: AsyncSession = Depends(get_session)) -> WebhookInfo:
    """Create or rotate the secret webhook token. The token is shown only once."""
    record = await _owned(session, user, workflow_id)
    definition = await store.get_version_definition(session, record.id, record.current_version) or {}
    trigger = next((n for n in definition.get("nodes", []) if n.get("operation") == "core.webhook_trigger"), None)
    method = (trigger or {}).get("config", {}).get("method", "POST")
    token = generate_token()
    record.webhook_token_hash = hash_token(token)
    await session.commit()
    return WebhookInfo(token=token, url=f"{get_settings().PUBLIC_BASE_URL}/api/webhooks/{record.id}/{token}",
                       method=method)


@router.delete("/{workflow_id}/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_webhook_token(workflow_id: str, user: User = Depends(get_current_user),
                               session: AsyncSession = Depends(get_session)) -> Response:
    record = await _owned(session, user, workflow_id)
    record.webhook_token_hash = None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------------- activation, forms, schedules
@router.patch("/{workflow_id}/active", response_model=WorkflowSummary)
async def set_active(workflow_id: str, payload: WorkflowActiveUpdate, user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)) -> WorkflowSummary:
    """Activate/deactivate the workflow's automatic triggers (webhook, form, schedule). Manual runs still work."""
    record = await _owned(session, user, workflow_id)
    record.active = payload.active
    await session.commit()
    await session.refresh(record)
    return WorkflowSummary(id=record.id, name=record.name, description=record.description,
                           version=record.current_version, has_webhook=bool(record.webhook_token_hash),
                           active=record.active, created_at=record.created_at, updated_at=record.updated_at)


def _form_info(record: Workflow, form: WorkflowForm) -> FormInfo:
    settings = get_settings()
    return FormInfo(node_id=form.node_id, form_id=form.id, url=f"{settings.PUBLIC_APP_URL}/forms/{form.id}",
                    api_url=f"{settings.PUBLIC_BASE_URL}/api/public/forms/{form.id}", enabled=form.enabled,
                    workflow_active=bool(record.active))


@router.get("/{workflow_id}/forms", response_model=List[FormInfo])
async def list_forms(workflow_id: str, user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)) -> List[FormInfo]:
    """Public form URLs of the saved workflow's Form Submission Trigger(s)."""
    record = await _owned(session, user, workflow_id)
    rows = await session.execute(select(WorkflowForm).where(WorkflowForm.workflow_id == record.id))
    return [_form_info(record, f) for f in rows.scalars()]


@router.post("/{workflow_id}/forms/{node_id}/rotate", response_model=FormInfo)
async def rotate_form(workflow_id: str, node_id: str, user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session)) -> FormInfo:
    """Issue a new public form id; the old URL stops working immediately."""
    from app.services.forms import new_form_id

    record = await _owned(session, user, workflow_id)
    form = (await session.execute(select(WorkflowForm).where(WorkflowForm.workflow_id == record.id,
                                                             WorkflowForm.node_id == node_id))).scalar_one_or_none()
    if form is None:
        raise HTTPException(status_code=404, detail="This workflow has no saved form for that node.")
    replacement = WorkflowForm(id=new_form_id(), workflow_id=record.id, user_id=record.user_id, node_id=node_id,
                               enabled=form.enabled)
    await session.delete(form)
    await session.flush()
    session.add(replacement)
    await session.commit()
    return _form_info(record, replacement)


@router.get("/{workflow_id}/schedules", response_model=List[ScheduleInfo])
async def list_schedules(workflow_id: str, user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session)) -> List[ScheduleInfo]:
    """Persisted schedule state: next/last run, last execution status, upcoming occurrences."""
    from app.services.schedules import next_runs, utcnow

    record = await _owned(session, user, workflow_id)
    rows = (await session.execute(select(WorkflowSchedule).where(WorkflowSchedule.workflow_id == record.id))).scalars()
    out: List[ScheduleInfo] = []
    for row in rows:
        last_status = row.last_status
        if row.last_execution_id:
            execution = await session.get(Execution, row.last_execution_id)
            if execution is not None and row.last_status == "started":
                last_status = execution.status
        upcoming = next_runs(row.spec, row.next_run_at or utcnow(), count=3,
                             anchor=row.next_run_at) if row.enabled and row.next_run_at else []
        out.append(ScheduleInfo(schedule_id=row.id, node_id=row.node_id, enabled=row.enabled,
                                workflow_active=bool(record.active), timezone=row.timezone, spec=row.spec,
                                next_run_at=row.next_run_at, last_run_at=row.last_run_at,
                                last_execution_id=row.last_execution_id, last_status=last_status,
                                last_error=row.last_error,
                                upcoming=([row.next_run_at] + upcoming[:2]) if row.next_run_at else []))
    return out


@router.post("/schedule-preview")
async def schedule_preview(payload: SchedulePreviewRequest, _user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Validate a Schedule Trigger config and list its next run times (nothing is persisted)."""
    from pydantic import ValidationError as PydanticValidationError

    from app.registry.configs import ScheduleTriggerConfig
    from app.services.schedules import compile_spec, next_runs, utcnow

    try:
        config = ScheduleTriggerConfig.model_validate(payload.config)
    except PydanticValidationError as exc:
        return {"valid": False, "errors": [str(e["msg"]).removeprefix("Value error, ") for e in exc.errors()],
                "next_runs": []}
    kind, value = compile_spec(config)
    now = utcnow()
    return {"valid": True, "errors": [], "kind": kind, "expression": value if kind == "cron" else None,
            "next_runs": [t.isoformat() for t in next_runs(config, now, count=payload.count, anchor=now)]}
