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
        self.CORS_ORIGINS: List[str] = _parse_origins(os.getenv("CORS_ORIGINS"))
        self.MAX_GENERATION_RETRIES: int = int(os.getenv("MAX_GENERATION_RETRIES", "2"))
        self.ENABLE_WORKFLOW_REVIEW: bool = _parse_bool(os.getenv("ENABLE_WORKFLOW_REVIEW"), default=False)
        self.MOCK_DEV_MODE: bool = _parse_bool(
            os.getenv("MOCK_DEV_MODE"),
            default=not (bool(self.GEMINI_API_KEY) and self.GEMINI_API_KEY != "your_gemini_api_key_here"),
        )

    @property
    def has_gemini_api_key(self) -> bool:
        return bool(self.GEMINI_API_KEY) and self.GEMINI_API_KEY != "your_gemini_api_key_here"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
