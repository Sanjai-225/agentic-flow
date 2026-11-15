"""Shared test configuration.

Automated tests are deterministic: they force MOCK_DEV_MODE (no Gemini calls),
use a throwaway SQLite database and talk to a real local HTTP server for HTTP
node tests. Tests that need live external providers are marked ``live`` and are
skipped unless explicitly selected with ``-m live``.
"""

import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator

_TMP_DIR = Path(tempfile.mkdtemp(prefix="agentic_flow_tests_"))

# Provider keys from backend/.env are exposed ONLY as LIVE_* variables for opt-in live tests
# (pytest -m live); the default suite never sees them and never calls a real provider.
try:
    from dotenv import dotenv_values

    _dotenv = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
except Exception:  # pragma: no cover - dotenv is a runtime dependency
    _dotenv = {}
for _name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    _value = (os.environ.get(_name) or _dotenv.get(_name) or "").strip()
    if _value.lower().startswith("your_") or "placeholder" in _value.lower():
        _value = ""  # template placeholder from .env: no real key, live tests for this provider are skipped
    if _value and not os.environ.get(f"LIVE_{_name}"):
        os.environ[f"LIVE_{_name}"] = _value

# Optional: run the whole suite against a real PostgreSQL database (e.g. a disposable local server) with
# TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/agentic_flow_test. The database name must contain
# "test" so a production DATABASE_URL can never be used by accident. Default: a throwaway SQLite file.
_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
if _TEST_DB_URL:
    from sqlalchemy.engine import make_url as _make_url

    if "test" not in (_make_url(_TEST_DB_URL.replace("postgres://", "postgresql://", 1)).database or ""):
        raise RuntimeError("TEST_DATABASE_URL must point at a disposable database whose name contains 'test'.")

os.environ.update(
    {
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "GEMINI_API_KEY": "",
        "MOCK_DEV_MODE": "true",
        "APP_ENV": "test",
        "DATABASE_URL": _TEST_DB_URL or f"sqlite+aiosqlite:///{(_TMP_DIR / 'test.db').as_posix()}",
        "JWT_SECRET": "test-jwt-secret-not-for-production",
        "HTTP_ALLOW_PRIVATE_NETWORKS": "true",
        # The background schedule loop is off in the suite for determinism; scheduler tests drive the real
        # Scheduler explicitly (ticks and a short-poll loop).
        "SCHEDULER_ENABLED": "false",
        "PUBLIC_BASE_URL": "http://testserver",
    }
)

import pytest  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: requires real external services/credentials (opt-in with -m live)")


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    if "live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live test: run with -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def app_client() -> Iterator[TestClient]:
    """TestClient with the app lifespan running (migrations + execution manager)."""
    with TestClient(app) as client:
        yield client


def register(client: TestClient, email: str | None = None, password: str = "correct-horse-battery") -> Dict[str, str]:
    email = email or f"user_{uuid.uuid4().hex[:10]}@example.com"
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def auth_headers(app_client: TestClient) -> Dict[str, str]:
    return register(app_client)


def wait_for_execution(client: TestClient, headers: Dict[str, str], execution_id: str,
                       timeout: float = 15.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = client.get(f"/api/executions/{execution_id}", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        if body["status"] in {"completed", "failed", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Execution {execution_id} did not finish within {timeout}s")


# ---------------------------------------------------------------- local HTTP server
_echo = FastAPI()
_calls: Dict[str, int] = {}


@_echo.api_route("/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def _echo_route(request: Request) -> JSONResponse:
    body = await request.body()
    return JSONResponse({
        "method": request.method,
        "query": dict(request.query_params),
        "headers": {k: v for k, v in request.headers.items()},
        "body": body.decode() if body else None,
    })


@_echo.get("/json")
async def _json() -> JSONResponse:
    return JSONResponse({"items": [{"id": 1, "status": "active"}, {"id": 2, "status": "inactive"},
                                   {"id": 3, "status": "active"}], "count": 3})


@_echo.get("/text")
async def _text() -> PlainTextResponse:
    return PlainTextResponse("plain response")


@_echo.get("/status/{code}")
async def _status(code: int) -> JSONResponse:
    return JSONResponse({"code": code}, status_code=code)


@_echo.get("/flaky/{key}")
async def _flaky(key: str) -> JSONResponse:
    """Fails with 503 twice per key, then succeeds."""
    _calls[key] = _calls.get(key, 0) + 1
    if _calls[key] <= 2:
        return JSONResponse({"attempt": _calls[key]}, status_code=503)
    return JSONResponse({"attempt": _calls[key], "ok": True})


@_echo.post("/count/{key}")
async def _count(key: str) -> JSONResponse:
    _calls[key] = _calls.get(key, 0) + 1
    return JSONResponse({"calls": _calls[key]}, status_code=503)


@_echo.get("/slow")
async def _slow() -> JSONResponse:
    import asyncio

    await asyncio.sleep(3)
    return JSONResponse({"slow": True})


@_echo.get("/redirect")
async def _redirect() -> RedirectResponse:
    return RedirectResponse("/json", status_code=302)


@_echo.get("/bearer")
async def _bearer(request: Request) -> JSONResponse:
    auth = request.headers.get("authorization", "")
    if auth != "Bearer s3cret-token":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"authorized": True})


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def http_server() -> Iterator[str]:
    """A real HTTP server on 127.0.0.1 for HTTP Request node tests."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_echo, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "local test HTTP server failed to start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def call_counts() -> Dict[str, int]:
    return _calls
