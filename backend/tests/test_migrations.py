"""Alembic migrations create exactly the schema described by the ORM models."""

import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db.models import Base
from app.db.session import run_migrations


def test_migrations_match_models():
    db = Path(tempfile.mkdtemp()) / "migrate.db"
    run_migrations(f"sqlite+aiosqlite:///{db.as_posix()}")
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert {"users", "workflows", "workflow_versions", "executions", "node_executions", "execution_logs",
                "credentials", "alembic_version"} <= tables
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], diff
