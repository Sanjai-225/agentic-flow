"""FastAPI application entry point for the AI Workflow Designer backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.workflow import router as workflow_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="AI Workflow Designer API",
    description="Generates and validates structured workflow graphs from natural-language requirements.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflow_router)
