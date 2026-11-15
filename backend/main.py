"""Compatibility entry point (`uvicorn main:app`). Production uses `uvicorn app.main:app` (render.yaml, Dockerfile)."""

from app.main import app

__all__ = ["app"]

