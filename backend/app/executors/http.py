"""HTTP Request executor (httpx) with SSRF protection, size limits and redirect checks."""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.net import ensure_url_allowed
from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.contracts import ExecutionContext, NodeExecutionResult, NodeExecutor
from app.engine.expressions import to_text
from app.executors import register
from app.registry.configs import HttpRequestConfig

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_REDIRECTS = 5
USER_AGENT = "AgenticFlow/1.0 (+workflow-engine)"
_CREDENTIAL_TYPE_FOR_AUTH = {"bearer": "http_bearer", "basic": "http_basic", "header": "http_header"}


# SSRF guard shared with the agent's read-only HTTP tool (app.core.net); re-exported for compatibility.
__all__ = ["ensure_url_allowed"]


def _stringify_map(values: Dict[str, Any]) -> Dict[str, str]:
    return {str(k): to_text(v) for k, v in values.items() if v is not None}


async def _apply_auth(config: HttpRequestConfig, headers: Dict[str, str], ctx: ExecutionContext) -> None:
    if config.auth.type == "none":
        return
    if not config.auth.credential_id:
        raise NodeExecutionError(
            ErrorCategory.MISSING_CREDENTIALS,
            f"Authentication type '{config.auth.type}' requires a credential.",
            field="auth.credential_id",
        )
    expected = _CREDENTIAL_TYPE_FOR_AUTH[config.auth.type]
    data = await ctx.credentials.get(config.auth.credential_id, [expected])
    if config.auth.type == "bearer":
        headers["Authorization"] = f"Bearer {data.get('token', '')}"
    elif config.auth.type == "basic":
        raw = f"{data.get('username', '')}:{data.get('password', '')}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    elif config.auth.type == "header":
        name = str(data.get("name") or "").strip()
        if not name:
            raise NodeExecutionError(ErrorCategory.MISSING_CREDENTIALS, "Header credential has no header name.",
                                     field="auth.credential_id")
        headers[name] = str(data.get("value", ""))


def _build_body(config: HttpRequestConfig) -> Dict[str, Any]:
    if config.body_type == "none" or config.body is None or config.method in {"GET", "HEAD"}:
        return {}
    if config.body_type == "json":
        body = config.body
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as exc:
                raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, f"Body is not valid JSON: {exc.msg}",
                                         field="body") from exc
        return {"json": body}
    if config.body_type == "form":
        if not isinstance(config.body, dict):
            raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, "Form body must be an object.", field="body")
        return {"data": _stringify_map(config.body)}
    return {"content": config.body if isinstance(config.body, str) else json.dumps(config.body)}


async def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            raise NodeExecutionError(
                ErrorCategory.PROVIDER_ERROR,
                f"Response body exceeds the {limit // (1024 * 1024)} MB limit.",
                suggestion="Request a smaller resource or use pagination.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_body(raw: bytes, response: httpx.Response, fmt: str) -> Any:
    text = raw.decode(response.encoding or "utf-8", errors="replace")
    content_type = response.headers.get("content-type", "")
    if fmt == "text":
        return text
    if fmt == "json" or (fmt == "auto" and "json" in content_type):
        if not text.strip():
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            if fmt == "json":
                raise NodeExecutionError(
                    ErrorCategory.PROVIDER_ERROR,
                    f"Response is not valid JSON: {exc.msg}.",
                    suggestion="Set response format to 'text' or 'auto'.",
                    details={"preview": text[:500]},
                ) from exc
            return text
    return text


def _status_error(status: int, output: Dict[str, Any]) -> NodeExecutionError:
    preview = output.get("body")
    preview_text = (preview if isinstance(preview, str) else json.dumps(preview, default=str))[:2000] if preview is not None else ""
    details = {"status_code": status, "response_preview": preview_text}
    if status in (401, 403):
        return NodeExecutionError(ErrorCategory.AUTH_FAILURE,
                                  f"The server rejected the request with HTTP {status}.",
                                  suggestion="Check the credential and the endpoint permissions.", details=details)
    if status == 429:
        return NodeExecutionError(ErrorCategory.RATE_LIMIT, "The server is rate limiting requests (HTTP 429).",
                                  retryable=True, details=details)
    if status == 408:
        return NodeExecutionError(ErrorCategory.TIMEOUT, "The server timed out the request (HTTP 408).",
                                  retryable=True, details=details)
    if status >= 500:
        return NodeExecutionError(ErrorCategory.PROVIDER_ERROR, f"The server returned HTTP {status}.",
                                  retryable=True, details=details)
    return NodeExecutionError(ErrorCategory.PROVIDER_ERROR, f"The server returned HTTP {status}.",
                              suggestion="Check the URL, method, query parameters and body.", details=details)


@register
class HttpRequestExecutor(NodeExecutor):
    operation_id = "http.request"
    config_model = HttpRequestConfig

    def has_side_effects(self, config: BaseModel, default: bool) -> bool:
        assert isinstance(config, HttpRequestConfig)
        return config.method not in SAFE_METHODS

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, HttpRequestConfig)
        settings = ctx.settings or get_settings()
        allow_private = bool(settings.HTTP_ALLOW_PRIVATE_NETWORKS)
        limit = int(settings.HTTP_MAX_RESPONSE_BYTES)

        try:
            url = httpx.URL(config.url.strip())
        except (httpx.InvalidURL, TypeError) as exc:
            raise NodeExecutionError(ErrorCategory.SCHEMA_VALIDATION, f"Invalid URL: {exc}", field="url") from exc

        headers = {"User-Agent": USER_AGENT, **_stringify_map(config.headers)}
        await _apply_auth(config, headers, ctx)
        params = _stringify_map(config.query)
        body_kwargs = _build_body(config)
        method = config.method
        started = time.perf_counter()

        async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds), follow_redirects=False) as client:
            current_url = url
            response: Optional[httpx.Response] = None
            for hop in range(MAX_REDIRECTS + 1):
                await ensure_url_allowed(current_url, allow_private)
                request = client.build_request(
                    method, current_url, headers=headers, params=params if hop == 0 else None,
                    **(body_kwargs if hop == 0 or method not in {"GET", "HEAD"} else {}),
                )
                try:
                    response = await client.send(request, stream=True)
                except httpx.TimeoutException as exc:
                    raise NodeExecutionError(
                        ErrorCategory.TIMEOUT,
                        f"Request timed out after {config.timeout_seconds:g}s.",
                        retryable=True, technical_detail=type(exc).__name__,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise NodeExecutionError(
                        ErrorCategory.PROVIDER_ERROR,
                        f"Could not connect to {current_url.host}: {type(exc).__name__}.",
                        retryable=True, technical_detail=str(exc)[:500],
                    ) from exc

                if config.follow_redirects and response.is_redirect and hop < MAX_REDIRECTS:
                    location = response.headers.get("location", "")
                    await response.aclose()
                    current_url = current_url.join(location)
                    if response.status_code == 303 or (response.status_code in (301, 302) and method == "POST"):
                        method, body_kwargs = "GET", {}
                    ctx.logger.info("Following redirect", {"status": response.status_code, "to": str(current_url)})
                    continue
                break

            assert response is not None
            try:
                raw = await _read_limited(response, limit)
            finally:
                await response.aclose()

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        output: Dict[str, Any] = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": _parse_body(raw, response, config.response_format),
            "url": str(response.url),
            "elapsed_ms": elapsed_ms,
        }
        ctx.logger.info(f"{method} {response.url} -> {response.status_code}", {"elapsed_ms": elapsed_ms})

        if not response.is_success and not (response.is_redirect and not config.follow_redirects):
            if not config.ignore_http_errors:
                err = _status_error(response.status_code, output)
                err.error.details["response"] = {k: output[k] for k in ("status_code", "url", "elapsed_ms")}
                raise err
        return NodeExecutionResult(output=output, metadata={"status_code": response.status_code,
                                                            "elapsed_ms": elapsed_ms})
