"""AI provider catalogue, agent tool catalogue and usage records (user-scoped)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.catalog import PROVIDERS, list_models, platform_key
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.models import AiUsageRecord, User
from app.db.session import get_session

router = APIRouter(prefix="/api/ai", tags=["AI"])


@router.get("/providers")
async def list_providers(_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Supported providers, their verified models and capabilities.

    ``platform_key_available`` is a boolean only: platform keys are never exposed.
    """
    settings = get_settings()
    out = []
    for pid, info in PROVIDERS.items():
        out.append({
            "id": pid, "label": info.label, "credential_type": info.credential_type, "docs_url": info.docs_url,
            "platform_key_available": bool(platform_key(pid)) and settings.AI_ALLOW_PLATFORM_KEYS,
            "models": [m.model_dump() for m in list_models(pid)],
        })
    return out


@router.get("/tools")
async def list_tools(_user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    """Tools the AI Agent may be granted (each must still be selected per node)."""
    from app.ai.tools import get_tool_registry

    return [t.public_view() for t in get_tool_registry().list_tools()]


@router.get("/usage")
async def list_usage(execution_id: Optional[str] = Query(None), limit: int = Query(100, ge=1, le=500),
                     user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)) -> List[Dict[str, Any]]:
    """Provider-reported model usage for the current user's executions (never estimated)."""
    stmt = select(AiUsageRecord).where(AiUsageRecord.user_id == user.id)
    if execution_id:
        stmt = stmt.where(AiUsageRecord.execution_id == execution_id)
    rows = await session.execute(stmt.order_by(AiUsageRecord.created_at.desc()).limit(limit))
    return [{
        "execution_id": r.execution_id, "workflow_id": r.workflow_id, "node_id": r.node_id,
        "operation": r.operation, "provider": r.provider, "model": r.model, "credential_source": r.credential_source,
        "status": r.status, "error_category": r.error_category, "fallback_used": r.fallback_used,
        "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "total_tokens": r.total_tokens,
        "duration_ms": r.duration_ms, "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows.scalars()]
