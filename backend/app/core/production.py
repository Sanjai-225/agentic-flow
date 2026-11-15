"""Production configuration checks.

``check_settings`` inspects the effective settings and returns problems by *name* only; secret values are
never included in messages. ``APP_ENV=production`` refuses to start while any ``error`` remains (see
``app.main.lifespan``); warnings are logged. The same checks back ``scripts/validate_environment.py``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse

from app.core.config import Settings
from app.db.url import DatabaseUrlError, parse_database_url

MIN_JWT_SECRET_LENGTH = 32
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


@dataclass(frozen=True)
class ConfigIssue:
    level: str  # "error" | "warning"
    name: str  # environment variable the issue is about
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.name}: {self.message}"


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".local")


def _check_public_url(name: str, value: str, issues: List[ConfigIssue]) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        issues.append(ConfigIssue("error", name, "must be an absolute http(s) URL."))
    elif _is_local(value):
        issues.append(ConfigIssue("error", name, "points at localhost; set the real public URL."))
    elif parsed.scheme != "https":
        issues.append(ConfigIssue("error", name, "must use https in production."))
    elif parsed.path not in {"", "/"}:
        issues.append(ConfigIssue("warning", name, "should be the origin only (no path)."))


def check_settings(settings: Settings, *, production: bool | None = None) -> List[ConfigIssue]:
    """Return configuration issues. With ``production`` (default: ``settings.is_production``) the strict rules apply."""
    strict = settings.is_production if production is None else production
    issues: List[ConfigIssue] = []

    # --- database -------------------------------------------------------------------------------------------
    try:
        db = parse_database_url(settings.DATABASE_URL)
    except DatabaseUrlError as exc:
        issues.append(ConfigIssue("error", "DATABASE_URL", str(exc)))
        db = None
    if strict and db is not None:
        if db.is_sqlite and not os.getenv("DATABASE_URL", "").strip():
            issues.append(ConfigIssue("error", "DATABASE_URL", "is not set (empty), so the app fell back to a local "
                                      "SQLite file. Paste the Supabase session pooler connection string."))
        elif db.is_sqlite:
            issues.append(ConfigIssue("error", "DATABASE_URL", "SQLite is not supported in production (the hosting "
                                      "filesystem is ephemeral). Use the Supabase PostgreSQL connection string."))
        elif "[YOUR-PASSWORD]" in settings.DATABASE_URL.upper() or "<" in settings.DATABASE_URL:
            issues.append(ConfigIssue("error", "DATABASE_URL", "still contains a placeholder such as [YOUR-PASSWORD]; "
                                      "put the real database password in its place."))
        elif db.ssl_mode in {None, "disable", "allow", "prefer"} and not _is_local(f"//{db.async_url.host}"):
            issues.append(ConfigIssue("error", "DATABASE_URL", "connections to a hosted database must use TLS "
                                      "(sslmode=require or stricter)."))
        if db.transaction_pooler:
            issues.append(ConfigIssue("warning", "DATABASE_URL", "uses the transaction pooler (port 6543). The session "
                                      "pooler (port 5432) is recommended for this long-running backend."))
    if strict and settings.DB_AUTO_MIGRATE:
        issues.append(ConfigIssue("warning", "DB_AUTO_MIGRATE", "is on: pending migrations are applied at startup. "
                                  "Releases must keep migrations additive; back up before deploying schema changes."))
    if settings.DB_POOL_SIZE < 1 or settings.DB_MAX_OVERFLOW < 0:
        issues.append(ConfigIssue("error", "DB_POOL_SIZE", "pool size must be >= 1 and overflow >= 0."))

    # --- secrets --------------------------------------------------------------------------------------------
    if strict:
        if not settings.JWT_SECRET:
            issues.append(ConfigIssue("error", "JWT_SECRET", "is not set."))
        elif len(settings.JWT_SECRET) < MIN_JWT_SECRET_LENGTH:
            issues.append(ConfigIssue("error", "JWT_SECRET", f"must be at least {MIN_JWT_SECRET_LENGTH} characters."))
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if key:
        try:
            from cryptography.fernet import Fernet

            Fernet(key.encode())
        except Exception:  # noqa: BLE001 - never echo the key
            issues.append(ConfigIssue("error", "CREDENTIALS_ENCRYPTION_KEY", "is not a valid Fernet key "
                                      "(generate one with scripts/generate_secrets.py)."))
    elif strict:
        issues.append(ConfigIssue("error", "CREDENTIALS_ENCRYPTION_KEY", "is not set. It must be set once and never "
                                  "changed, or stored credentials become unreadable."))

    # --- URLs and CORS --------------------------------------------------------------------------------------
    if strict:
        _check_public_url("PUBLIC_BASE_URL", settings.PUBLIC_BASE_URL, issues)
        _check_public_url("PUBLIC_APP_URL", settings.PUBLIC_APP_URL, issues)
        if "*" in settings.CORS_ORIGINS:
            issues.append(ConfigIssue("error", "CORS_ORIGINS", "must list the frontend origin(s); '*' is not allowed."))
        else:
            for origin in settings.CORS_ORIGINS:
                _check_public_url("CORS_ORIGINS", origin, issues)
    if settings.CORS_ORIGIN_REGEX:
        try:
            pattern = re.compile(settings.CORS_ORIGIN_REGEX)
        except re.error:
            issues.append(ConfigIssue("error", "CORS_ORIGIN_REGEX", "is not a valid regular expression."))
        else:
            if pattern.fullmatch("https://attacker-example.vercel.app") or pattern.fullmatch("http://evil.example"):
                issues.append(ConfigIssue("warning" if not strict else "error", "CORS_ORIGIN_REGEX",
                                          "matches origins outside this project; anchor it to your project's "
                                          "preview URL pattern."))

    # --- runtime behaviour ----------------------------------------------------------------------------------
    if strict:
        if settings.HTTP_ALLOW_PRIVATE_NETWORKS:
            issues.append(ConfigIssue("error", "HTTP_ALLOW_PRIVATE_NETWORKS", "must be false in production (SSRF)."))
        if settings.MOCK_DEV_MODE:
            issues.append(ConfigIssue("warning", "GEMINI_API_KEY", "is not set (or MOCK_DEV_MODE=true): the AI "
                                      "workflow designer returns labelled mock workflows."))
        if settings.AI_ALLOW_PLATFORM_KEYS:
            issues.append(ConfigIssue("warning", "AI_ALLOW_PLATFORM_KEYS", "is on: every user's AI nodes may spend the "
                                      "platform's provider keys."))
        if not settings.SCHEDULER_ENABLED:
            issues.append(ConfigIssue("warning", "SCHEDULER_ENABLED", "is off: Schedule Triggers will not fire."))
    return issues


def errors(issues: List[ConfigIssue]) -> List[ConfigIssue]:
    return [i for i in issues if i.level == "error"]
