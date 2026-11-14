"""FastAPI application entry point for the AI Workflow Designer backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.registry import router as registry_router
from app.api.workflow import router as workflow_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title="AI Workflow Designer API",
    description="Generates and validates structured workflow graphs from natural-language requirements.",
    version="1.0.0",
)

cors_kwargs = {
    "allow_methods": ["*"],
    "allow_headers": ["*"],
}

if "*" in settings.CORS_ORIGINS:
    cors_kwargs["allow_origins"] = ["*"]
    cors_kwargs["allow_credentials"] = False
else:
    cors_kwargs["allow_origins"] = settings.CORS_ORIGINS
    cors_kwargs["allow_credentials"] = True
    cors_kwargs["allow_origin_regex"] = r"https://.*\.vercel\.app"

app.add_middleware(CORSMiddleware, **cors_kwargs)

app.include_router(workflow_router)
app.include_router(registry_router)
