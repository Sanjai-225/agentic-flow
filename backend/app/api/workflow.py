"""API routes for health checks and workflow generation."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.workflow import GenerateWorkflowRequest
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
) -> Dict[str, Any]:
    """Generate, validate, and optionally review a workflow graph from a natural-language prompt.

    Returns the workflow JSON with optional semantic review metadata.
    """
    try:
        return generator.generate(prompt=payload.prompt, enable_review=payload.review)
    except LLMConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
