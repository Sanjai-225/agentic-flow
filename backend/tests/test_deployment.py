"""Production-readiness: DATABASE_URL handling, production config checks, readiness, CORS, RLS migration."""

import importlib.util
import ssl
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.production import check_settings, errors
from app.db.models import Base
from app.db.session import ensure_schema_current, migration_status, run_migrations, sync_database_url
from app.db.url import DatabaseUrlError, parse_database_url, redact_database_url

BACKEND = Path(__file__).resolve().parents[1]
SUPABASE_SESSION = "postgresql://postgres.abcdefgh:pa%40ss%25word@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
SUPABASE_TXN = "postgresql://postgres.abcdefgh:secretpw@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"


# ------------------------------------------------------------------------------------------ DATABASE_URL
def test_sqlite_urls_map_to_async_and_sync_drivers():
    cfg = parse_database_url("sqlite+aiosqlite:///./agentic_flow.db")
    assert cfg.is_sqlite
    assert cfg.async_url.drivername == "sqlite+aiosqlite"
    assert cfg.sync_url.drivername == "sqlite"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg", "postgresql+asyncpg"])
def test_postgres_scheme_aliases(scheme):
    cfg = parse_database_url(f"{scheme}://u:p@db.example.com:5432/app")
    assert cfg.is_postgresql
    assert cfg.async_url.drivername == "postgresql+asyncpg"
    assert cfg.sync_url.drivername == "postgresql+psycopg"


def test_supabase_session_pooler_defaults_to_tls_and_keeps_encoded_password():
    cfg = parse_database_url(SUPABASE_SESSION)
    assert cfg.ssl_mode == "require" and not cfg.transaction_pooler
    assert isinstance(cfg.async_connect_args["ssl"], ssl.SSLContext)
    assert "statement_cache_size" not in cfg.async_connect_args
    assert cfg.async_url.password == "pa@ss%word"  # URL-decoded once, re-encoded by SQLAlchemy
    assert "sslmode=require" in sync_database_url(SUPABASE_SESSION)
    assert "sslmode" not in cfg.async_url.query  # asyncpg does not accept libpq's sslmode


def test_transaction_pooler_disables_prepared_statement_caches():
    for url in (SUPABASE_TXN, SUPABASE_SESSION + "?pgbouncer=true"):
        args = parse_database_url(url).async_connect_args
        assert args["statement_cache_size"] == 0 and args["prepared_statement_cache_size"] == 0
        assert callable(args["prepared_statement_name_func"])


def test_local_postgres_without_sslmode_has_no_tls_and_explicit_disable_is_respected():
    assert parse_database_url("postgresql://u:p@localhost:5432/agentic_flow_test").ssl_mode is None
    cfg = parse_database_url("postgresql://u:p@db.example.com/app?sslmode=disable")
    assert cfg.async_connect_args["ssl"] is False


@pytest.mark.parametrize("bad", ["", "mysql://u:p@h/db", "postgresql://u:p@h/db?sslmode=bogus", "not a url"])
def test_invalid_database_urls_are_rejected_without_echoing_secrets(bad):
    with pytest.raises(DatabaseUrlError) as exc:
        parse_database_url(bad)
    assert "p@h" not in str(exc.value)


def test_redacted_url_never_contains_password():
    shown = redact_database_url(SUPABASE_TXN)
    assert "secretpw" not in shown and "***" in shown


# ------------------------------------------------------------------------------------------ migrations
def test_migration_status_and_schema_guard(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}"
    before = migration_status(url)
    assert not before["up_to_date"] and before["pending"][0] == "0001" and before["pending"][-1] == before["heads"][0]
    with pytest.raises(RuntimeError, match="deploy_migrations.py"):
        ensure_schema_current(url)
    run_migrations(url)
    after = migration_status(url)
    assert after["up_to_date"] and after["pending"] == []
    ensure_schema_current(url)
    run_migrations(url)  # idempotent re-run


def test_schema_newer_than_code_allows_rollback(tmp_path):
    from sqlalchemy import create_engine, text

    url = f"sqlite+aiosqlite:///{(tmp_path / 'r.db').as_posix()}"
    run_migrations(url)
    engine = create_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '9999_future'"))
    engine.dispose()
    status = migration_status(url)
    assert status["ahead"] and status["pending"] == [] and not status["up_to_date"]
    ensure_schema_current(url)  # previous code may start on a newer additive schema


def test_rls_migration_covers_every_application_table():
    path = BACKEND / "alembic" / "versions" / "0003_postgres_row_level_security.py"
    spec = importlib.util.spec_from_file_location("m0003", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    missing = set(Base.metadata.tables) - set(module.TABLES)
    assert not missing, f"enable RLS for new tables in a migration (and list them here): {missing}"


# ------------------------------------------------------------------------------------------ production checks
def _settings(monkeypatch, **env) -> Settings:
    for key in ("PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL", "CORS_ORIGIN_REGEX", "MOCK_DEV_MODE",
                "AI_ALLOW_PLATFORM_KEYS", "DB_AUTO_MIGRATE", "HTTP_ALLOW_PRIVATE_NETWORKS"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings()


def _valid_production_env() -> dict:
    return {
        "APP_ENV": "production",
        "DATABASE_URL": SUPABASE_SESSION,
        "DB_AUTO_MIGRATE": "false",
        "JWT_SECRET": "x" * 48,
        "CREDENTIALS_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "PUBLIC_BASE_URL": "https://agentic-flow-api.onrender.com",
        "PUBLIC_APP_URL": "https://agentic-flow.vercel.app",
        "CORS_ORIGINS": "https://agentic-flow.vercel.app",
        "HTTP_ALLOW_PRIVATE_NETWORKS": "false",
        "GEMINI_API_KEY": "real-looking-key",
        "MOCK_DEV_MODE": "false",
        "AI_ALLOW_PLATFORM_KEYS": "false",
        "SCHEDULER_ENABLED": "true",
    }


def test_valid_production_configuration_has_no_issues(monkeypatch):
    issues = check_settings(_settings(monkeypatch, **_valid_production_env()))
    assert issues == [], [str(i) for i in issues]


def test_development_defaults_fail_production_checks(monkeypatch):
    env = _valid_production_env()
    env.update(DATABASE_URL="sqlite+aiosqlite:///./x.db", JWT_SECRET="short", CREDENTIALS_ENCRYPTION_KEY="",
               PUBLIC_BASE_URL="http://localhost:8000", PUBLIC_APP_URL="http://localhost:3000",
               CORS_ORIGINS="*", HTTP_ALLOW_PRIVATE_NETWORKS="true")
    names = {i.name for i in errors(check_settings(_settings(monkeypatch, **env)))}
    assert names == {"DATABASE_URL", "JWT_SECRET", "CREDENTIALS_ENCRYPTION_KEY", "PUBLIC_BASE_URL",
                     "PUBLIC_APP_URL", "CORS_ORIGINS", "HTTP_ALLOW_PRIVATE_NETWORKS"}


def test_issue_messages_never_contain_secret_values(monkeypatch):
    env = _valid_production_env()
    env.update(CREDENTIALS_ENCRYPTION_KEY="not-a-fernet-key-SECRETVALUE", JWT_SECRET="SECRETSHORT",
               DATABASE_URL="postgresql://u:DBSECRET@db.example.com/app?sslmode=disable")
    text = " ".join(str(i) for i in check_settings(_settings(monkeypatch, **env)))
    assert "SECRETVALUE" not in text and "SECRETSHORT" not in text and "DBSECRET" not in text
    assert "CREDENTIALS_ENCRYPTION_KEY" in text and "JWT_SECRET" in text and "TLS" in text


def test_broad_cors_regex_is_rejected_in_production(monkeypatch):
    env = _valid_production_env()
    env["CORS_ORIGIN_REGEX"] = r"https://.*\.vercel\.app"
    assert any(i.name == "CORS_ORIGIN_REGEX" for i in errors(check_settings(_settings(monkeypatch, **env))))
    env["CORS_ORIGIN_REGEX"] = r"https://agentic-flow-git-[a-z0-9-]+-myteam\.vercel\.app"
    assert check_settings(_settings(monkeypatch, **env)) == []


def test_public_base_url_falls_back_to_render_external_url(monkeypatch):
    s = _settings(monkeypatch, RENDER_EXTERNAL_URL="https://agentic-flow-api.onrender.com/")
    assert s.PUBLIC_BASE_URL == "https://agentic-flow-api.onrender.com"
    s = _settings(monkeypatch, RENDER_EXTERNAL_URL="https://a.onrender.com", PUBLIC_BASE_URL="https://api.example.com")
    assert s.PUBLIC_BASE_URL == "https://api.example.com"


# ------------------------------------------------------------------------------------------ HTTP surface
def test_readiness_reports_database_and_schema(app_client):
    res = app_client.get("/health/ready")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] is True and body["checks"]["schema_up_to_date"] is True
    assert "DATABASE_URL" not in res.text and "sqlite" not in res.text.lower()
    assert app_client.get("/health").json() == {"status": "healthy"}


def test_cors_allows_configured_origin_only(app_client):
    def preflight(origin: str):
        return app_client.options("/api/workflows", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization"})

    ok = preflight("http://localhost:3000")
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-credentials" not in ok.headers  # bearer tokens, never cookies
    for foreign in ("https://attacker-example.vercel.app", "https://evil.example"):
        assert "access-control-allow-origin" not in preflight(foreign).headers

