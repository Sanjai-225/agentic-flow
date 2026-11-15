"""Check database connectivity, TLS, migration state and Supabase hardening. Read-only.

Usage (PowerShell, from backend/):
    python scripts/check_database.py --prompt-url                  # asks for DATABASE_URL (input hidden)
    python scripts/check_database.py --env-file ..\\deploy\\production.env
    python scripts/check_database.py --use-local-dotenv            # local development database

Checks: connection, server version, TLS on the connection, Alembic revision (current vs head), expected
tables, row level security on every application table (PostgreSQL), connection limits, and a write probe
inside a transaction that is always rolled back (``--write-probe``). Never modifies data or schema.
"""

from __future__ import annotations

import argparse
import os
import time

from _deploy_common import FAIL, INFO, PASS, SKIP, WARN, Report, add_env_args, prepare_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_env_args(parser)
    parser.add_argument("--prompt-url", action="store_true", help="prompt for DATABASE_URL if it is not set")
    parser.add_argument("--write-probe", action="store_true",
                        help="insert into a TEMP table inside a transaction that is rolled back")
    args = parser.parse_args()
    prepare_environment(args.env_file, prompt_database_url=args.prompt_url, isolate=not args.use_local_dotenv)

    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.pool import NullPool

    from app.core.config import Settings
    from app.db.models import Base
    from app.db.session import migration_status
    from app.db.url import DatabaseUrlError, parse_database_url, redact_database_url

    report = Report()
    url = os.environ.get("DATABASE_URL", "").strip() or Settings().DATABASE_URL
    try:
        cfg = parse_database_url(url)
    except DatabaseUrlError as exc:
        report.add(FAIL, "DATABASE_URL parses", str(exc))
        return report.finish("Database check")
    report.add(PASS, "DATABASE_URL parses", redact_database_url(url))
    if cfg.is_postgresql:
        report.add(INFO, "connection mode", "transaction pooler (6543)" if cfg.transaction_pooler
                   else "direct or session pooler")
        report.add(PASS if cfg.ssl_mode in {"require", "verify-ca", "verify-full"} or
                   (cfg.async_url.host or "") in {"localhost", "127.0.0.1"} else WARN,
                   "sslmode", cfg.ssl_mode or "none (local server)")

    engine = create_engine(cfg.sync_url, poolclass=NullPool)
    try:
        started = time.perf_counter()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            report.add(PASS, "connect", f"{(time.perf_counter() - started) * 1000:.0f} ms")
            if cfg.is_postgresql:
                version = conn.execute(text("SHOW server_version")).scalar()
                report.add(INFO, "server version", str(version))
                ssl_on = conn.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()
                report.add(PASS if ssl_on else (WARN if cfg.ssl_mode is None else FAIL), "TLS on this connection",
                           str(bool(ssl_on)))
                max_conn = conn.execute(text("SHOW max_connections")).scalar()
                report.add(INFO, "server max_connections", str(max_conn))

            tables = set(inspect(conn).get_table_names())
            expected = set(Base.metadata.tables)
            missing = sorted(expected - tables)
            if not tables & expected:
                report.add(WARN, "application tables", "none yet - run scripts/deploy_migrations.py --apply")
            elif missing:
                report.add(FAIL, "application tables", "missing: " + ", ".join(missing))
            else:
                report.add(PASS, "application tables", f"{len(expected)} present")

            if cfg.is_postgresql and tables & expected:
                rows = conn.execute(text(
                    "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relkind = 'r'")).all()
                no_rls = sorted(name for name, rls in rows if not rls and name in expected | {"alembic_version"})
                report.add(PASS if not no_rls else FAIL, "row level security (Supabase Data API lockdown)",
                           "enabled on all application tables" if not no_rls else "disabled on: " + ", ".join(no_rls))

            if args.write_probe:
                conn.rollback()  # end the implicit read transaction before an explicit one
                trans = conn.begin()
                try:
                    conn.execute(text("CREATE TEMP TABLE af_write_probe (id integer)"))
                    conn.execute(text("INSERT INTO af_write_probe (id) VALUES (1)"))
                    ok = conn.execute(text("SELECT count(*) FROM af_write_probe")).scalar() == 1
                    report.add(PASS if ok else FAIL, "write probe (rolled back)")
                finally:
                    trans.rollback()
            else:
                report.add(SKIP, "write probe", "pass --write-probe to run it")
    except Exception as exc:  # noqa: BLE001 - show the class and a short, host-free hint
        report.add(FAIL, "connect", f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        return report.finish("Database check")
    finally:
        engine.dispose()

    status = migration_status(url)
    if status["up_to_date"]:
        report.add(PASS, "migrations", f"at head {status['heads']}")
    else:
        report.add(WARN, "migrations", f"current={status['current'] or 'empty'} pending={status['pending']} - "
                   "apply with scripts/deploy_migrations.py --apply")
    return report.finish("Database check")


if __name__ == "__main__":
    raise SystemExit(main())
