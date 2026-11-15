"""API routes for health checks and workflow generation."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_current_user
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
