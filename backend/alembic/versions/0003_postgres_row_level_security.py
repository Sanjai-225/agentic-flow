"""PostgreSQL: enable row level security on application tables (Supabase Data API lockdown)

Supabase exposes the ``public`` schema through its auto-generated Data API (PostgREST) to the ``anon`` and
``authenticated`` roles, whose API key is public by design. Agentic Flow never uses that API: the backend
connects as the table owner, which bypasses RLS. Enabling RLS with *no* policies therefore denies every
Data API request to these tables while leaving the application unaffected.

Additive and idempotent; a no-op on SQLite. Downgrade disables RLS again.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table created by migrations 0001-0002, plus Alembic's own bookkeeping table.
TABLES = (
    "users",
    "workflows",
    "workflow_versions",
    "executions",
    "node_executions",
    "execution_logs",
    "credentials",
    "ai_usage_records",
    "workflow_forms",
    "workflow_schedules",
    "schedule_occurrences",
    "alembic_version",
)


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
