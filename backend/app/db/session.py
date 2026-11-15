"""Async engine/session management and schema migration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.url import parse_database_url

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def _configure_sqlite(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def engine_options(url: str) -> Dict[str, Any]:
    """create_async_engine keyword arguments for ``url`` (pooling, connection recovery, driver args)."""
    settings = get_settings()
    cfg = parse_database_url(url)
    options: Dict[str, Any] = {"connect_args": dict(cfg.async_connect_args)}
    if cfg.is_postgresql:
        options.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
            # Recycle before the pooler/network drops idle connections; pre-ping recovers from a
            # connection that died anyway (database restart, failover, pooler restart).
            pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
            pool_pre_ping=True,
        )
    return options


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        url = get_settings().DATABASE_URL
        cfg = parse_database_url(url)
        _engine = create_async_engine(cfg.async_url, **engine_options(url))
        if cfg.is_sqlite:
            _configure_sqlite(_engine)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    async with get_sessionmaker()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def sync_database_url(url: str) -> str:
    """Alembic runs synchronously: the sync-driver form of ``url`` (sqlite / postgresql+psycopg)."""
    return parse_database_url(url).sync_url.render_as_string(hide_password=False)


def _alembic_config(url: Optional[str] = None):  # type: ignore[no-untyped-def]
    from alembic.config import Config

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    # ConfigParser interpolation: a literal '%' (URL-encoded password) must be doubled.
    cfg.set_main_option("sqlalchemy.url", sync_database_url(url or get_settings().DATABASE_URL).replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


def migration_status(url: Optional[str] = None) -> Dict[str, Any]:
    """Current vs head Alembic revision of the database at ``url`` (blocking; read-only)."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    cfg = _alembic_config(url)
    script = ScriptDirectory.from_config(cfg)
    heads = list(script.get_heads())
    engine = create_engine(parse_database_url(url or get_settings().DATABASE_URL).sync_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            current = list(MigrationContext.configure(conn).get_current_heads())
    finally:
        engine.dispose()
    up_to_date = set(current) == set(heads)
    known = {rev.revision for rev in script.walk_revisions()}
    # A revision this code does not know means the database was migrated by NEWER code (e.g. after a rollback).
    ahead = bool(current) and any(rev not in known for rev in current)
    pending: List[str] = []
    if not up_to_date and not ahead:
        lower = current[0] if len(current) == 1 else "base"
        pending = [rev.revision for rev in script.iterate_revisions("heads", lower)][::-1]
    return {"current": current, "heads": heads, "pending": pending, "up_to_date": up_to_date, "ahead": ahead}


def run_migrations(url: Optional[str] = None) -> None:
    """Upgrade the database schema to the latest Alembic revision (blocking)."""
    from alembic import command

    command.upgrade(_alembic_config(url), "head")


def ensure_schema_current(url: Optional[str] = None) -> None:
    """Fail fast when automatic migration is disabled and the schema is behind the code (blocking)."""
    status = migration_status(url)
    if status["ahead"]:
        # Code rollback onto a newer (additive-only) schema: allowed, but make it visible.
        logging.getLogger(__name__).warning(
            "Database schema %s is newer than this code (%s); continuing (migrations are additive).",
            status["current"], status["heads"])
        return
    if not status["up_to_date"]:
        raise RuntimeError(
            "Database schema is not at the latest migration "
            f"(current={status['current'] or 'empty'}, expected={status['heads']}). "
            "Apply migrations first: python scripts/deploy_migrations.py --apply "
            "(see docs/PRODUCTION_DEPLOYMENT.md), or set DB_AUTO_MIGRATE=true."
        )
