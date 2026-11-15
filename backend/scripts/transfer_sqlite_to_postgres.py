"""OPTIONAL one-time copy of a local SQLite database into an EMPTY, migrated PostgreSQL database.

Only needed if you want to keep data created locally (users, workflows, executions, credentials...).
A fresh production start needs none of this.

Usage (PowerShell, from backend/):
    # 0. back up the SQLite file:   Copy-Item .\\agentic_flow.db .\\agentic_flow.backup.db
    # 1. migrate the target:        python scripts/deploy_migrations.py --prompt-url --apply
    # 2. dry run (counts only):     python scripts/transfer_sqlite_to_postgres.py --source .\\agentic_flow.backup.db --prompt-url
    # 3. copy:                      python scripts/transfer_sqlite_to_postgres.py --source .\\agentic_flow.backup.db --prompt-url --apply

Rules:
  * The target must be at the same migration head as the source and contain NO rows in any application
    table; otherwise nothing is written (never merges, never overwrites, never deletes).
  * Everything is copied in one transaction: any error rolls the whole copy back.
  * Row counts are compared table by table afterwards; integer id sequences are advanced past copied ids.
  * Stored credentials are encrypted with the SOURCE environment's CREDENTIALS_ENCRYPTION_KEY. Production
    must use that same key to read them, or pass --skip-credentials and let users re-enter their keys.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from _deploy_common import FAIL, INFO, PASS, WARN, Report, prepare_environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="path to the SQLite file (use a backup copy)")
    parser.add_argument("--env-file", help="dotenv file holding the target DATABASE_URL")
    parser.add_argument("--prompt-url", action="store_true", help="prompt for the target DATABASE_URL")
    parser.add_argument("--apply", action="store_true", help="copy the data (default: dry run)")
    parser.add_argument("--skip-credentials", action="store_true", help="do not copy stored credentials")
    args = parser.parse_args()
    prepare_environment(args.env_file, prompt_database_url=args.prompt_url)

    from sqlalchemy import Integer, create_engine, func, select, text
    from sqlalchemy.pool import NullPool

    from app.db.models import Base
    from app.db.session import migration_status
    from app.db.url import parse_database_url, redact_database_url

    report = Report()
    source = Path(args.source).resolve()
    if not source.is_file():
        report.add(FAIL, "source file", f"not found: {source}")
        return report.finish("Transfer")
    source_url = f"sqlite+aiosqlite:///{source.as_posix()}"
    target_url = os.environ.get("DATABASE_URL", "").strip()
    if not target_url:
        report.add(FAIL, "target DATABASE_URL", "not set (use --prompt-url or --env-file)")
        return report.finish("Transfer")
    target_cfg = parse_database_url(target_url)
    report.add(INFO, "source", str(source))
    report.add(INFO, "target", redact_database_url(target_url))

    src_status, dst_status = migration_status(source_url), migration_status(target_url)
    if not src_status["up_to_date"]:
        report.add(FAIL, "source schema", f"at {src_status['current']}, head is {src_status['heads']}: start the "
                   "app once locally (auto-migrates) on a copy of the file, then retry")
        return report.finish("Transfer")
    if not dst_status["up_to_date"]:
        report.add(FAIL, "target schema", "not at head: run scripts/deploy_migrations.py --apply first")
        return report.finish("Transfer")
    report.add(PASS, "both schemas at head", ", ".join(dst_status["heads"]))

    tables = [t for t in Base.metadata.sorted_tables if not (args.skip_credentials and t.name == "credentials")]
    src = create_engine(parse_database_url(source_url).sync_url, poolclass=NullPool)
    dst = create_engine(target_cfg.sync_url, poolclass=NullPool)
    try:
        with src.connect() as s, dst.connect() as d:
            counts = {t.name: s.execute(select(func.count()).select_from(t)).scalar_one() for t in tables}
            non_empty = [t.name for t in tables if d.execute(select(func.count()).select_from(t)).scalar_one()]
            for name, n in counts.items():
                report.add(INFO, f"source rows: {name}", str(n))
            if non_empty:
                report.add(FAIL, "target is empty", "rows already present in: " + ", ".join(non_empty)
                           + " - refusing to merge")
                return report.finish("Transfer")
            report.add(PASS, "target is empty")
            if args.skip_credentials:
                report.add(WARN, "credentials", "skipped: users must re-enter provider keys")
            else:
                report.add(WARN, "credentials", "copied as ciphertext: production needs the SAME "
                           "CREDENTIALS_ENCRYPTION_KEY as the source environment")
            if not args.apply:
                report.add(INFO, "dry run", "nothing was written. Re-run with --apply to copy.")
                return report.finish("Transfer")

            d.rollback()
            with d.begin():
                if target_cfg.is_postgresql:
                    d.execute(text("SET LOCAL TIME ZONE 'UTC'"))  # SQLite stores naive UTC timestamps
                for table in tables:
                    rows = [dict(r._mapping) for r in s.execute(select(table))]
                    for start in range(0, len(rows), 500):
                        d.execute(table.insert(), rows[start:start + 500])
                if target_cfg.is_postgresql:
                    for table in tables:
                        pk = list(table.primary_key.columns)
                        if len(pk) == 1 and isinstance(pk[0].type, Integer):  # serial ids only
                            d.execute(text(
                                f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "
                                f"COALESCE((SELECT MAX({pk[0].name}) FROM {table.name}), 0) + 1, false)"))
            for table in tables:
                copied = d.execute(select(func.count()).select_from(table)).scalar_one()
                report.add(PASS if copied == counts[table.name] else FAIL, f"rows match: {table.name}",
                           f"{copied}/{counts[table.name]}")
    except Exception as exc:  # noqa: BLE001 - the transaction was rolled back
        report.add(FAIL, "copy", f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]} (rolled back)")
    finally:
        src.dispose()
        dst.dispose()
    return report.finish("Transfer")


if __name__ == "__main__":
    raise SystemExit(main())
