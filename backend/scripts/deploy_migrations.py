"""Inspect and (only when explicitly approved) apply Alembic migrations to a database.

Usage (PowerShell, from backend/):
    python scripts/deploy_migrations.py --prompt-url                 # DRY RUN: current revision + pending list
    python scripts/deploy_migrations.py --prompt-url --sql           # also print the SQL that would run
    python scripts/deploy_migrations.py --prompt-url --apply         # apply after typing the confirmation

Safety rules:
  * Default is a dry run. Nothing is written without --apply AND an interactive confirmation (or --yes).
  * Only upgrades to head are supported; downgrades are refused (restore a backup instead).
  * A pending migration that drops/renames tables or columns, or truncates/deletes data, is refused unless
    --allow-destructive is given explicitly.
  * Take a backup first (Supabase: Database > Backups, or pg_dump - see docs/PRODUCTION_DEPLOYMENT.md).
"""

from __future__ import annotations

import argparse
import io
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

from _deploy_common import BACKEND_DIR, FAIL, INFO, PASS, WARN, Report, add_env_args, prepare_environment

DESTRUCTIVE = re.compile(
    r"\b(op\.drop_table|op\.drop_column|batch_op\.drop_column|op\.rename_table|op\.alter_column\([^)]*new_column_name|"
    r"batch_op\.alter_column\([^)]*new_column_name|DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE|DELETE\s+FROM)\b",
    re.IGNORECASE,
)


def upgrade_body(path: Path) -> str:
    """Source of a migration's upgrade() function (downgrade() legitimately drops things)."""
    text = path.read_text(encoding="utf-8")
    start = text.find("def upgrade(")
    end = text.find("def downgrade(", start)
    return text[start:end if end != -1 else None] if start != -1 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_env_args(parser)
    parser.add_argument("--prompt-url", action="store_true", help="prompt for DATABASE_URL if it is not set")
    parser.add_argument("--sql", action="store_true", help="print the SQL of the pending migrations (offline mode)")
    parser.add_argument("--apply", action="store_true", help="apply pending migrations (asks for confirmation)")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation (CI use)")
    parser.add_argument("--allow-destructive", action="store_true",
                        help="permit pending migrations that drop/rename/delete (backup first!)")
    args = parser.parse_args()
    prepare_environment(args.env_file, prompt_database_url=args.prompt_url, isolate=not args.use_local_dotenv)

    from alembic import command
    from alembic.script import ScriptDirectory
    from alembic.util.exc import CommandError

    from app.core.config import Settings
    from app.db.session import _alembic_config, migration_status, run_migrations
    from app.db.url import DatabaseUrlError, parse_database_url, redact_database_url

    report = Report()
    url = os.environ.get("DATABASE_URL", "").strip() or Settings().DATABASE_URL
    try:
        parse_database_url(url)
    except DatabaseUrlError as exc:
        report.add(FAIL, "DATABASE_URL", str(exc))
        return report.finish("Migrations")
    report.add(INFO, "target", redact_database_url(url))

    try:
        status = migration_status(url)
    except Exception as exc:  # noqa: BLE001
        report.add(FAIL, "read migration state", f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        return report.finish("Migrations")
    report.add(INFO, "current revision", ", ".join(status["current"]) or "empty database")
    report.add(INFO, "head revision", ", ".join(status["heads"]))
    if len(status["current"]) > 1 or len(status["heads"]) > 1:
        report.add(FAIL, "linear history", "multiple heads/branches; resolve before deploying")
        return report.finish("Migrations")
    known = {rev.revision for rev in ScriptDirectory.from_config(_alembic_config(url)).walk_revisions()}
    if status["current"] and status["current"][0] not in known:
        report.add(FAIL, "known revision", "the database is at a revision this code does not know (newer code "
                   "deployed earlier?). Refusing: downgrades are not supported - deploy the matching code.")
        return report.finish("Migrations")
    if status["up_to_date"]:
        report.add(PASS, "schema", "already at head - nothing to apply")
        return report.finish("Migrations")

    script = ScriptDirectory.from_config(_alembic_config(url))
    destructive = []
    for rev_id in status["pending"]:
        rev = script.get_revision(rev_id)
        body = upgrade_body(Path(rev.path))
        flagged = sorted({m.group(1) for m in DESTRUCTIVE.finditer(body)})
        doc = (rev.doc or "").splitlines()[0] if rev.doc else ""
        report.add(WARN if flagged else INFO, f"pending {rev_id}", doc + (f"  DESTRUCTIVE: {flagged}" if flagged else ""))
        if flagged:
            destructive.append(rev_id)

    if args.sql:
        lower = status["current"][0] if status["current"] else None
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                command.upgrade(_alembic_config(url), f"{lower}:head" if lower else "head", sql=True)
        except CommandError as exc:  # SQLite batch migrations need a live connection to reflect tables
            report.add(WARN, "SQL preview", f"not available for this database: {str(exc).splitlines()[0][:160]}")
        else:
            print("\n----- SQL that --apply would execute (review, do not run by hand) -----")
            print(buf.getvalue())
            print("----- end SQL -----\n")

    if not args.apply:
        report.add(INFO, "dry run", "nothing was changed. Re-run with --apply to apply the pending migrations.")
        return report.finish("Migrations")
    if destructive and not args.allow_destructive:
        report.add(FAIL, "destructive migrations", f"{destructive} need --allow-destructive (take a backup first)")
        return report.finish("Migrations")
    if not args.yes:
        if not sys.stdin.isatty():
            report.add(FAIL, "confirmation", "no interactive terminal; pass --yes to confirm explicitly")
            return report.finish("Migrations")
        print(f"About to apply {len(status['pending'])} migration(s): {', '.join(status['pending'])}")
        print("Have you taken a backup of this database? Type APPLY to continue: ", end="", flush=True)
        if input().strip() != "APPLY":
            report.add(FAIL, "confirmation", "not confirmed - nothing was changed")
            return report.finish("Migrations")

    try:
        run_migrations(url)
    except Exception as exc:  # noqa: BLE001 - Alembic runs each migration in a transaction (PostgreSQL)
        report.add(FAIL, "apply", f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        return report.finish("Migrations")
    after = migration_status(url)
    report.add(PASS if after["up_to_date"] else FAIL, "schema after apply", ", ".join(after["current"]))
    return report.finish("Migrations")


if __name__ == "__main__":
    os.chdir(BACKEND_DIR)
    raise SystemExit(main())
