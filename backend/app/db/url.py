"""DATABASE_URL normalisation for SQLite (local) and PostgreSQL (production, e.g. Supabase).

One environment variable, ``DATABASE_URL``, drives both the async application engine and the
synchronous Alembic migration engine. Operators may paste a provider connection string as-is:

* ``postgres://`` / ``postgresql://`` / ``postgresql+psycopg://`` / ``postgresql+asyncpg://`` are accepted.
  The app uses ``asyncpg``; Alembic uses ``psycopg`` (v3).
* ``sslmode`` is translated for asyncpg (which does not understand libpq's ``sslmode`` parameter) and
  kept for psycopg. Hosted PostgreSQL defaults to ``sslmode=require`` when no mode is given and the host
  is not local.
* Supabase's *transaction* pooler (port 6543, or ``?pgbouncer=true``) does not support prepared
  statements, so asyncpg's statement caches are disabled there. The *session* pooler (port 5432) is the
  recommended mode for a long-running backend and needs no special handling.

Nothing in here ever logs or returns the password except inside the URL objects handed to SQLAlchemy;
use :func:`redact_database_url` for anything that is displayed.
"""

from __future__ import annotations

import ssl
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict

from sqlalchemy.engine import URL, make_url

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}
_SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
TRANSACTION_POOLER_PORT = 6543


class DatabaseUrlError(ValueError):
    """DATABASE_URL is malformed or uses an unsupported database."""


@dataclass(frozen=True)
class DatabaseConfig:
    backend: str  # "sqlite" | "postgresql"
    async_url: URL
    sync_url: URL
    async_connect_args: Dict[str, Any] = field(default_factory=dict)
    transaction_pooler: bool = False
    ssl_mode: str | None = None

    @property
    def is_sqlite(self) -> bool:
        return self.backend == "sqlite"

    @property
    def is_postgresql(self) -> bool:
        return self.backend == "postgresql"


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _asyncpg_ssl(mode: str) -> Any:
    """Map a libpq sslmode to asyncpg's ``ssl`` connect argument."""
    if mode == "disable":
        return False
    if mode in {"allow", "prefer"}:
        return mode
    if mode == "require":
        # libpq semantics: encrypt, but do not verify the server certificate.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    # verify-ca / verify-full: verify against the system trust store (+ hostname for verify-full).
    ctx = ssl.create_default_context()
    ctx.check_hostname = mode == "verify-full"
    return ctx


def clean_database_url(raw: str) -> str:
    """Undo common copy-paste slips: surrounding whitespace/quotes and a pasted ``DATABASE_URL=`` prefix."""
    text = (raw or "").strip()
    if text.upper().startswith("DATABASE_URL="):
        text = text[len("DATABASE_URL="):].strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def parse_database_url(raw: str) -> DatabaseConfig:
    """Normalise ``raw`` into async (app) and sync (Alembic) SQLAlchemy URLs."""
    text = clean_database_url(raw)
    if not text:
        raise DatabaseUrlError("DATABASE_URL is empty.")
    if text.startswith("postgres://"):  # Heroku/Render-style scheme alias
        text = "postgresql://" + text[len("postgres://"):]
    try:
        url = make_url(text)
    except Exception as exc:  # noqa: BLE001 - never echo the URL (it contains the password)
        raise DatabaseUrlError("DATABASE_URL could not be parsed. Check the scheme, host and URL-encoding "
                               "of special characters in the password.") from exc

    backend = url.get_backend_name()
    if backend == "sqlite":
        return DatabaseConfig(
            backend="sqlite",
            async_url=url.set(drivername="sqlite+aiosqlite"),
            sync_url=url.set(drivername="sqlite"),
            async_connect_args={"timeout": 30},
        )
    if backend != "postgresql":
        raise DatabaseUrlError(f"Unsupported database backend '{backend}'. Use PostgreSQL or SQLite.")

    query = dict(url.query)
    ssl_mode = str(query.pop("sslmode", "") or "").strip().lower() or None
    pgbouncer = _truthy(query.pop("pgbouncer", "false"))
    query.pop("ssl", None)  # asyncpg-style flag; normalised through ssl_mode instead
    if ssl_mode is not None and ssl_mode not in _SSL_MODES:
        raise DatabaseUrlError(f"Unsupported sslmode '{ssl_mode}'.")
    if ssl_mode is None and (url.host or "") not in _LOCAL_HOSTS:
        ssl_mode = "require"  # hosted PostgreSQL (Supabase) requires TLS

    transaction_pooler = pgbouncer or url.port == TRANSACTION_POOLER_PORT
    base = url.set(query=query)

    connect_args: Dict[str, Any] = {"timeout": 15, "command_timeout": 60}
    if ssl_mode is not None:
        connect_args["ssl"] = _asyncpg_ssl(ssl_mode)
    if transaction_pooler:
        # PgBouncer/Supavisor transaction mode: prepared statements cannot be reused across transactions.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__af_{uuid.uuid4().hex}__"

    sync_query = dict(query)
    if ssl_mode is not None:
        sync_query["sslmode"] = ssl_mode
    sync_query.setdefault("connect_timeout", "15")
    return DatabaseConfig(
        backend="postgresql",
        async_url=base.set(drivername="postgresql+asyncpg"),
        sync_url=base.set(drivername="postgresql+psycopg", query=sync_query),
        async_connect_args=connect_args,
        transaction_pooler=transaction_pooler,
        ssl_mode=ssl_mode,
    )


def redact_database_url(raw: str) -> str:
    """Display form of a database URL with the password hidden (safe for logs and reports)."""
    try:
        cfg = parse_database_url(raw)
    except DatabaseUrlError as exc:
        return f"<invalid DATABASE_URL: {exc}>"
    if cfg.is_sqlite:
        return f"sqlite (file: {cfg.async_url.database})"
    return cfg.async_url.render_as_string(hide_password=True)
