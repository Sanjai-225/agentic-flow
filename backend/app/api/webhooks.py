"""Public webhook ingress. Authenticated by the workflow's secret token (stored hashed)."""

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_manager
from app.core.config import get_settings
from app.core.ratelimit import client_ip, limiter
from app.core.security import token_matches
from app.db.models import Workflow
from app.db.session import get_session
from app.engine.worker import ExecutionManager
from app.schemas.workflow import WorkflowSchema
from app.services import workflow_store as store

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])

_DROPPED_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-api-key", "set-cookie"}


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body too large.")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Webhook body too large.")
    return body


@router.api_route("/{workflow_id}/{token}", methods=["GET", "POST", "PUT"], status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(workflow_id: str, token: str, request: Request,
                          session: AsyncSession = Depends(get_session),
                          manager: ExecutionManager = Depends(get_manager)) -> Dict[str, Any]:
    allowed, retry_after = limiter.check(f"webhook:{workflow_id}:{client_ip(request)}",
                                         get_settings().WEBHOOK_RATE_LIMIT_PER_MINUTE)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many webhook requests.",
                            headers={"Retry-After": str(int(retry_after) + 1)})
    not_found = HTTPException(status_code=404, detail="Webhook not found.")
    record = await session.get(Workflow, workflow_id)
    if record is None or not token_matches(token, record.webhook_token_hash):
        raise not_found
    if not record.active:
        raise HTTPException(status_code=409, detail="This workflow is inactive; activate it to accept webhooks.")

    definition = await store.get_version_definition(session, record.id, record.current_version)
    workflow = WorkflowSchema.model_validate(definition)
    trigger = next((n for n in workflow.nodes if n.operation == "core.webhook_trigger"), None)
    if trigger is None:
        raise HTTPException(status_code=409, detail="This workflow does not start with a Webhook Trigger.")
    expected_method = str(trigger.config.get("method", "POST")).upper()
    if request.method != expected_method:
        raise HTTPException(status_code=405, detail=f"This webhook accepts {expected_method} requests.")

    raw = await _read_body(request, get_settings().WEBHOOK_MAX_BODY_BYTES)
    body: Any = None
    if raw:
        text = raw.decode("utf-8", errors="replace")
        if "json" in request.headers.get("content-type", ""):
            try:
                body = json.loads(text)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Request body is not valid JSON: {exc.msg}") from exc
        else:
            body = text
    payload = {
        "body": body,
        "headers": {k: v for k, v in request.headers.items() if k.lower() not in _DROPPED_HEADERS},
        "query": dict(request.query_params),
        "method": request.method,
    }

    plan = await store.plan_for_user(session, record.user_id, workflow)
    if not plan.valid:
        raise HTTPException(status_code=422, detail={
            "message": "The workflow behind this webhook is not runnable.",
            "issues": [{"category": i.category.value, "message": i.message, "node_id": i.node_id}
                       for i in plan.errors],
        })
    execution = await store.create_execution(session, record, "webhook", payload)
    manager.start(execution.id)
    return {"execution_id": execution.id, "status": execution.status}
