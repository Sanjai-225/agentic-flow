"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env from backend/ if present (falls back gracefully to process env)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
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
        self.JWT_SECRET: str = os.getenv("JWT_SECRET", "").strip()
        self.JWT_EXPIRES_MINUTES: int = int(os.getenv("JWT_EXPIRES_MINUTES", "720"))
        self.CREDENTIALS_ENCRYPTION_KEY: str = os.getenv("CREDENTIALS_ENCRYPTION_KEY", "").strip()
        self.HTTP_ALLOW_PRIVATE_NETWORKS: bool = _parse_bool(
            os.getenv("HTTP_ALLOW_PRIVATE_NETWORKS"), default=False
        )
        self.HTTP_MAX_RESPONSE_BYTES: int = int(os.getenv("HTTP_MAX_RESPONSE_BYTES", str(5 * 1024 * 1024)))
        self.PUBLIC_BASE_URL: str = (os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").strip()).rstrip("/")
        self.EXECUTION_MAX_DURATION_SECONDS: int = int(os.getenv("EXECUTION_MAX_DURATION_SECONDS", "900"))
        self.WEBHOOK_MAX_BODY_BYTES: int = int(os.getenv("WEBHOOK_MAX_BODY_BYTES", str(1024 * 1024)))

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
