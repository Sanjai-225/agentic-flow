"""Shared helpers for the deployment scripts (Windows PowerShell and POSIX shells).

Every script is run from ``backend/``:  ``python scripts/<name>.py --help``.
Secret values are never printed: only variable names, booleans and redacted URLs.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Plain ASCII output: works in Windows PowerShell 5.1 consoles with legacy code pages.
PASS, FAIL, WARN, INFO, SKIP = "PASS", "FAIL", "WARN", "INFO", "SKIP"


def read_env_file(path: Path) -> Dict[str, str]:
    """Parse a dotenv file without exporting it (python-dotenv semantics)."""
    from dotenv import dotenv_values

    if not path.is_file():
        raise SystemExit(f"{FAIL}: env file not found: {path}")
    return {k: (v or "") for k, v in dotenv_values(path).items()}


def prepare_environment(env_file: Optional[str], *, prompt_database_url: bool = False,
                        isolate: bool = True) -> None:
    """Load the environment that is being checked BEFORE app settings are imported.

    ``isolate`` stops ``backend/.env`` (local development values) from being merged in, so a production check
    only sees the values given by ``--env-file`` and the current process environment.
    """
    if isolate:
        os.environ["AGENTIC_FLOW_NO_DOTENV"] = "1"
    if env_file:
        for key, value in read_env_file(Path(env_file)).items():
            os.environ[key] = value
    if prompt_database_url and not os.environ.get("DATABASE_URL", "").strip():
        value = getpass.getpass("DATABASE_URL (input hidden): ").strip()
        if not value:
            raise SystemExit(f"{FAIL}: DATABASE_URL is required.")
        os.environ["DATABASE_URL"] = value


def add_env_args(parser) -> None:  # type: ignore[no-untyped-def]
    parser.add_argument("--env-file", help="dotenv file with the values to check (never committed). "
                        "Without it, the current process environment is used.")
    parser.add_argument("--use-local-dotenv", action="store_true",
                        help="also load backend/.env (local development values). Off by default.")


class Report:
    def __init__(self) -> None:
        self.rows: List[tuple[str, str, str]] = []

    def add(self, status: str, check: str, detail: str = "") -> None:
        self.rows.append((status, check, detail))
        line = f"[{status}] {check}"
        print(line + (f" - {detail}" if detail else ""), flush=True)

    @property
    def failed(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == FAIL)

    @property
    def warned(self) -> int:
        return sum(1 for s, _, _ in self.rows if s == WARN)

    def finish(self, title: str) -> int:
        passed = sum(1 for s, _, _ in self.rows if s == PASS)
        print(f"\n{title}: {passed} passed, {self.failed} failed, {self.warned} warnings")
        return 1 if self.failed else 0
