"""API routes for health checks and workflow generation."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_sessionmaker, migration_status
from app.db.models import User

from app.schemas.workflow import GenerateWorkflowRequest
from app.services.llm_errors import classify_llm_error
from app.services.llm_service import LLMConfigurationError, LLMGenerationError
from app.services.workflow_generator import WorkflowGenerationError, WorkflowGenerator

router = APIRouter()


def get_workflow_generator() -> WorkflowGenerator:
    """Dependency provider for WorkflowGenerator."""
    return WorkflowGenerator()


@router.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Liveness check endpoint."""
    return {"status": "healthy"}


@router.get("/health/ready", tags=["Health"])
async def readiness_check(request: Request) -> JSONResponse:
    """Readiness: database reachable, schema at the latest migration, scheduler state. No secrets or URLs."""
    settings = get_settings()
    checks: Dict[str, Any] = {"database": False, "schema_up_to_date": False}
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
        status_info = await run_in_threadpool(migration_status, settings.DATABASE_URL)
        # A newer (additive-only) schema after a code rollback still serves this code.
        checks["schema_up_to_date"] = status_info["up_to_date"] or status_info["ahead"]
        checks["schema_ahead_of_code"] = status_info["ahead"]
        checks["schema_revision"] = status_info["current"]
    except Exception as exc:  # noqa: BLE001 - report the failure class only (messages may contain hosts)
        checks["database_error"] = type(exc).__name__
    scheduler = getattr(request.app.state, "scheduler", None)
    checks["scheduler"] = ("running" if scheduler is not None and scheduler.running else
                           "disabled" if not settings.SCHEDULER_ENABLED else "stopped")
    checks["environment"] = settings.APP_ENV
    ready = checks["database"] and checks["schema_up_to_date"]
    return JSONResponse({"status": "ready" if ready else "not_ready", "checks": checks}, status_code=200 if ready else 503)


@router.post(
    "/api/workflows/generate",
    status_code=status.HTTP_200_OK,
    tags=["Workflows"],
)
async def generate_workflow(
    payload: GenerateWorkflowRequest,
    generator: WorkflowGenerator = Depends(get_workflow_generator),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate, validate, and optionally review a workflow graph from a natural-language prompt.

    Returns the workflow JSON with optional semantic review metadata.
    """
    try:
        # The generator performs blocking network I/O; keep it off the event loop so
        # running workflow executions are not stalled.
        return await run_in_threadpool(generator.generate, prompt=payload.prompt, enable_review=payload.review)
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=classify_llm_error(exc).to_detail(),
        ) from exc
    except WorkflowGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": str(exc),
                "errors": exc.errors,
            },
        ) from exc
    except LLMGenerationError as exc:
        # Structured, secret-free detail: {category, message, suggestion, status_code, model}.
        detail = classify_llm_error(exc).to_detail()
        detail["message"] = str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=detail,
        ) from exc
