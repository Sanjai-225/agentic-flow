"""FastAPI application entry point for the Agentic Flow backend."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.credentials import router as credentials_router
from app.api.executions import router as executions_router
from app.api.registry import router as registry_router
from app.api.webhooks import router as webhooks_router
from app.api.workflow import router as workflow_router
from app.api.workflows import router as workflows_router
from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker, run_migrations
from app.engine.worker import ExecutionManager

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    current = get_settings()
    _ = current.effective_jwt_secret  # fail fast in production without JWT_SECRET
    if current.DB_AUTO_MIGRATE:
        await asyncio.to_thread(run_migrations, current.DATABASE_URL)
    manager = ExecutionManager(get_sessionmaker())
    await manager.reconcile_interrupted()
    app.state.execution_manager = manager
    try:
        yield
    finally:
        await manager.shutdown()
        app.state.execution_manager = None
        await dispose_engine()


app = FastAPI(
    title="Agentic Flow API",
    description="AI-assisted workflow designer and execution engine.",
    version="2.0.0",
    lifespan=lifespan,
)

cors_kwargs: dict = {
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
app.include_router(auth_router)
app.include_router(workflows_router)
app.include_router(executions_router)
app.include_router(webhooks_router)
app.include_router(credentials_router)
