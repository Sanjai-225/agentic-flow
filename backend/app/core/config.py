"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env from backend/ if present (falls back gracefully to process env). Deployment scripts that check a
# *different* environment (e.g. production values) set AGENTIC_FLOW_NO_DOTENV=1 so local values never mix in.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
if os.getenv("AGENTIC_FLOW_NO_DOTENV", "").strip().lower() not in {"1", "true", "yes"}:
    load_dotenv(_BACKEND_DIR / ".env")


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_origins(value: str | None) -> List[str]:
    if not value:
        return ["http://localhost:3000"]
    origins = [origin.strip() for origin in value.split(",") if origin.strip()]
    return origins or ["http://localhost:3000"]


class Settings:
    """Runtime settings for the AI Workflow Designer backend."""

    def __init__(self) -> None:
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
        self.GEMINI_FALLBACK_MODEL: str = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
        self.GEMINI_REVIEWER_MODEL: str = os.getenv("GEMINI_REVIEWER_MODEL", "gemma-4-31b-it").strip() or "gemma-4-31b-it"
        self.CORS_ORIGINS: List[str] = _parse_origins(os.getenv("CORS_ORIGINS"))
        # Optional regex for additional allowed origins (e.g. this project's Vercel preview URLs). Unset by default:
        # no wildcard origin is trusted unless the operator opts in.
        self.CORS_ORIGIN_REGEX: str = os.getenv("CORS_ORIGIN_REGEX", "").strip()
        self.MAX_GENERATION_RETRIES: int = int(os.getenv("MAX_GENERATION_RETRIES", "2"))
        self.MAX_REVIEW_CORRECTION_ATTEMPTS: int = int(os.getenv("MAX_REVIEW_CORRECTION_ATTEMPTS", "2"))
        self.ENABLE_WORKFLOW_REVIEW: bool = _parse_bool(os.getenv("ENABLE_WORKFLOW_REVIEW"), default=True)
        self.MOCK_DEV_MODE: bool = _parse_bool(
            os.getenv("MOCK_DEV_MODE"),
            default=not (bool(self.GEMINI_API_KEY) and self.GEMINI_API_KEY != "your_gemini_api_key_here"),
        )

        # --- Execution platform (Milestone 1) ---
        self.APP_ENV: str = (os.getenv("APP_ENV", "development").strip() or "development").lower()
        self.DATABASE_URL: str = (
            os.getenv("DATABASE_URL", "").strip()
            or f"sqlite+aiosqlite:///{(_BACKEND_DIR / 'agentic_flow.db').as_posix()}"
        )
        self.DB_AUTO_MIGRATE: bool = _parse_bool(os.getenv("DB_AUTO_MIGRATE"), default=True)
        # PostgreSQL connection pool (ignored for SQLite). Keep pool_size + max_overflow below the database /
        # pooler connection limit (Supabase session pooler: see docs/PRODUCTION_DEPLOYMENT.md).
        self.DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
        self.DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "5"))
        self.DB_POOL_TIMEOUT_SECONDS: float = float(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30"))
        self.DB_POOL_RECYCLE_SECONDS: int = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "300"))
        self.JWT_SECRET: str = os.getenv("JWT_SECRET", "").strip()
        self.JWT_EXPIRES_MINUTES: int = int(os.getenv("JWT_EXPIRES_MINUTES", "720"))
        self.CREDENTIALS_ENCRYPTION_KEY: str = os.getenv("CREDENTIALS_ENCRYPTION_KEY", "").strip()
        self.HTTP_ALLOW_PRIVATE_NETWORKS: bool = _parse_bool(
            os.getenv("HTTP_ALLOW_PRIVATE_NETWORKS"), default=False
        )
        self.HTTP_MAX_RESPONSE_BYTES: int = int(os.getenv("HTTP_MAX_RESPONSE_BYTES", str(5 * 1024 * 1024)))
        # Public URL of this backend (webhook + public form API links). On Render, RENDER_EXTERNAL_URL is provided
        # automatically and used when PUBLIC_BASE_URL is not set explicitly.
        self.PUBLIC_BASE_URL: str = (
            os.getenv("PUBLIC_BASE_URL", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip()
            or "http://localhost:8000"
        ).rstrip("/")
        # Public URL of the frontend (hosted form pages live at {PUBLIC_APP_URL}/forms/{form_id}).
        self.PUBLIC_APP_URL: str = (os.getenv("PUBLIC_APP_URL", "http://localhost:3000").strip()).rstrip("/")
        self.EXECUTION_MAX_DURATION_SECONDS: int = int(os.getenv("EXECUTION_MAX_DURATION_SECONDS", "900"))
        self.WEBHOOK_MAX_BODY_BYTES: int = int(os.getenv("WEBHOOK_MAX_BODY_BYTES", str(1024 * 1024)))

        # --- AI model providers (Milestone 2) ---
        # Platform-level keys: used by AI Generate / AI Agent nodes only when a node selects no user
        # credential AND AI_ALLOW_PLATFORM_KEYS is on (default: on outside production, off in production).
        self.OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
        self.ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.AI_ALLOW_PLATFORM_KEYS: bool = _parse_bool(os.getenv("AI_ALLOW_PLATFORM_KEYS"),
                                                        default=not self.is_production)
        # JSON list of operator-added models: [{"provider": "openai", "model": "...", ...capabilities}].
        self.AI_EXTRA_MODELS: str = os.getenv("AI_EXTRA_MODELS", "").strip()
        self.AI_MODEL_MAX_RETRIES: int = int(os.getenv("AI_MODEL_MAX_RETRIES", "2"))
        self.AI_MAX_TIMEOUT_SECONDS: float = float(os.getenv("AI_MAX_TIMEOUT_SECONDS", "300"))
        self.AGENT_DISABLED_TOOLS: List[str] = [
            t.strip() for t in os.getenv("AGENT_DISABLED_TOOLS", "").split(",") if t.strip()
        ]
        self.AGENT_ALLOW_NETWORK_TOOLS: bool = _parse_bool(os.getenv("AGENT_ALLOW_NETWORK_TOOLS"), default=True)

        # --- Triggers and flow nodes (Milestone 2) ---
        self.SCHEDULER_ENABLED: bool = _parse_bool(os.getenv("SCHEDULER_ENABLED"), default=True)
        self.SCHEDULER_POLL_SECONDS: float = float(os.getenv("SCHEDULER_POLL_SECONDS", "5"))
        self.SCHEDULE_MIN_INTERVAL_MINUTES: int = int(os.getenv("SCHEDULE_MIN_INTERVAL_MINUTES", "1"))
        self.FORM_MAX_BODY_BYTES: int = int(os.getenv("FORM_MAX_BODY_BYTES", str(64 * 1024)))
        self.FORM_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("FORM_RATE_LIMIT_PER_MINUTE", "10"))
        self.WEBHOOK_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("WEBHOOK_RATE_LIMIT_PER_MINUTE", "120"))
        self.LOOP_MAX_ITEMS: int = int(os.getenv("LOOP_MAX_ITEMS", "1000"))

    @property
    def is_production(self) -> bool:
        return self.APP_ENV in {"production", "prod"}

    @property
    def effective_jwt_secret(self) -> str:
        """JWT signing secret. A missing secret is only tolerated outside production."""
        if self.JWT_SECRET:
            return self.JWT_SECRET
        if self.is_production:
            raise RuntimeError("JWT_SECRET must be set when APP_ENV=production.")
        return "dev-insecure-jwt-secret-change-me"

    @property
    def has_gemini_api_key(self) -> bool:
        return bool(self.GEMINI_API_KEY) and self.GEMINI_API_KEY != "your_gemini_api_key_here"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
