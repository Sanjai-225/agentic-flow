"""Public (unauthenticated) Form Submission Trigger endpoints.

GET  /api/public/forms/{form_id}  -> sanitised form definition (title, description, fields only)
POST /api/public/forms/{form_id}  -> {"data": {...field values...}, "_hp": ""}

Protection: unguessable form ids, per-IP and per-form rate limits, a body size cap, a honeypot field,
server-side validation of every field, and responses that never include workflow configuration, node
ids, owner identity, execution ids or internal errors.
"""

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_manager
from app.core.config import get_settings
from app.core.ratelimit import client_ip, limiter
from app.db.models import Workflow, WorkflowForm
from app.db.session import get_session
from app.engine.worker import ExecutionManager
from app.schemas.workflow import WorkflowSchema
from app.services import workflow_store as store
from app.services.forms import HONEYPOT_FIELD, build_payload, public_definition, validate_submission

router = APIRouter(prefix="/api/public/forms", tags=["Public forms"])

_UNAVAILABLE = "This form is not available."


async def _load(session: AsyncSession, form_id: str) -> tuple[WorkflowForm, Workflow, Dict[str, Any]]:
    """Return (form, workflow, node config) or raise 404 without saying why (no information leak)."""
    not_found = HTTPException(status_code=404, detail=_UNAVAILABLE)
    if not form_id.startswith("frm_") or len(form_id) > 64:
        raise not_found
    form = await session.get(WorkflowForm, form_id)
    if form is None or not form.enabled:
        raise not_found
    record = await session.get(Workflow, form.workflow_id)
    if record is None or not record.active:
        raise not_found
    definition = await store.get_version_definition(session, record.id, record.current_version)
    node = next((n for n in (definition or {}).get("nodes", []) if n.get("id") == form.node_id
                 and n.get("operation") == "core.form_trigger"), None)
    if node is None:
        raise not_found
    return form, record, dict(node.get("config") or {})


@router.get("/{form_id}")
async def get_form(form_id: str, request: Request, session: AsyncSession = Depends(get_session)) -> Dict[str, Any]:
    allowed, retry_after = limiter.check(f"form-view:{client_ip(request)}", 120)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again shortly.",
                            headers={"Retry-After": str(int(retry_after) + 1)})
    form, _record, config = await _load(session, form_id)
    return public_definition(form.id, config)


async def _read_json(request: Request, limit: int) -> Any:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail="The submission is too large.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(status_code=413, detail="The submission is too large.")
    if "json" not in request.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="Submit the form as JSON.")
    try:
        return json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="The submission is not valid JSON.") from exc


@router.post("/{form_id}", status_code=status.HTTP_202_ACCEPTED)
async def submit_form(form_id: str, request: Request, session: AsyncSession = Depends(get_session),
                      manager: ExecutionManager = Depends(get_manager)) -> Any:
    settings = get_settings()
    ip = client_ip(request)
    for key, limit in ((f"form-submit-ip:{ip}", settings.FORM_RATE_LIMIT_PER_MINUTE),
                       (f"form-submit-form:{form_id}", settings.FORM_RATE_LIMIT_PER_MINUTE * 10)):
        allowed, retry_after = limiter.check(key, limit)
        if not allowed:
            raise HTTPException(status_code=429, detail="Too many submissions. Please try again shortly.",
                                headers={"Retry-After": str(int(retry_after) + 1)})
    payload = await _read_json(request, settings.FORM_MAX_BODY_BYTES)
    form, record, config = await _load(session, form_id)
    data = payload.get("data") if isinstance(payload, dict) else None
    honeypot = payload.get(HONEYPOT_FIELD) if isinstance(payload, dict) else None
    success = {"ok": True, "message": config.get("success_message") or "Thank you!"}
    if honeypot:
        # Bot filled the hidden field: answer like a success, but never start a workflow.
        return success
    clean, errors = validate_submission(config, data)
    if errors:
        return JSONResponse(status_code=422, content={"ok": False, "message": "Please correct the highlighted "
                                                      "fields.", "errors": errors})
    workflow = WorkflowSchema.model_validate(await store.get_version_definition(session, record.id,
                                                                                record.current_version))
    plan = await store.plan_for_user(session, record.user_id, workflow)
    if not plan.valid:
        # The owner sees the validation problems in the editor; the public only learns it is unavailable.
        raise HTTPException(status_code=503, detail="This form cannot accept submissions right now.")
    execution = await store.create_execution(session, record, "form", build_payload(form.id, clean))
    manager.start(execution.id)
    return success
