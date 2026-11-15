"""FastAPI application entry point for the Agentic Flow backend."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai import router as ai_router
from app.api.auth import router as auth_router
from app.api.credentials import router as credentials_router
from app.api.executions import router as executions_router
from app.api.public_forms import router as public_forms_router
from app.api.registry import router as registry_router
from app.api.webhooks import router as webhooks_router
from app.api.workflow import router as workflow_router
from app.api.workflows import router as workflows_router
from app.core.config import get_settings
from app.core.production import check_settings
from app.core.production import errors as config_errors
from app.db.session import dispose_engine, ensure_schema_current, get_sessionmaker, run_migrations
from app.engine.scheduler import Scheduler
from app.engine.worker import ExecutionManager

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    current = get_settings()
    issues = check_settings(current)
    for issue in issues:
        logger.warning("Configuration: %s", issue)
    if current.is_production and config_errors(issues):
        # Names only - values are never logged. See scripts/validate_environment.py.
        # Messages describe the problem only; they never contain the values.
        raise RuntimeError("Refusing to start with APP_ENV=production: "
                           + " | ".join(f"{i.name}: {i.message}" for i in config_errors(issues)))
    _ = current.effective_jwt_secret  # fail fast in production without JWT_SECRET
    if current.DB_AUTO_MIGRATE:
        await asyncio.to_thread(run_migrations, current.DATABASE_URL)
    else:
        await asyncio.to_thread(ensure_schema_current, current.DATABASE_URL)
    manager = ExecutionManager(get_sessionmaker())
    await manager.reconcile_interrupted()
    app.state.execution_manager = manager
    scheduler = Scheduler(get_sessionmaker(), manager)
    app.state.scheduler = scheduler
    if current.SCHEDULER_ENABLED:
        scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()
        await manager.shutdown()
        app.state.execution_manager = None
        await dispose_engine()


app = FastAPI(
    title="Agentic Flow API",
    description="AI-assisted workflow designer and execution engine.",
    version="2.0.0",
    lifespan=lifespan,
)

# Browsers authenticate with a Bearer token (no cookies), so credentialed CORS is never needed.
# Allowed origins come only from configuration: CORS_ORIGINS (exact) and the optional CORS_ORIGIN_REGEX.
cors_kwargs: dict = {
    "allow_methods": ["*"],
    "allow_headers": ["*"],
    "allow_credentials": False,
    "allow_origins": ["*"] if "*" in settings.CORS_ORIGINS else settings.CORS_ORIGINS,
    "max_age": 600,
}
if settings.CORS_ORIGIN_REGEX:
    cors_kwargs["allow_origin_regex"] = settings.CORS_ORIGIN_REGEX

app.add_middleware(CORSMiddleware, **cors_kwargs)

app.include_router(workflow_router)
app.include_router(registry_router)
app.include_router(auth_router)
app.include_router(workflows_router)
app.include_router(executions_router)
app.include_router(webhooks_router)
app.include_router(credentials_router)
app.include_router(ai_router)
app.include_router(public_forms_router)
