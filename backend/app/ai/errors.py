"""Normalisation of provider SDK exceptions into the workflow error taxonomy.

OpenAI, Anthropic and Google SDKs raise different exception classes; LangChain
sometimes wraps them. ``classify_provider_error`` walks the exception chain,
reads the HTTP status / class name and returns a ``ProviderFailure`` that says:

- which ``ErrorCategory`` applies (auth vs availability vs timeout vs config),
- whether retrying the same model can help (``retryable``),
- whether switching to the configured fallback model is allowed
  (``fallback_eligible``; only availability problems qualify, never auth,
  permission, configuration, cancellation, tool or output-validation errors).

Messages never include API keys: every provider text passes through ``scrub``.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from app.core.errors import ErrorCategory, NodeExecutionError

_KEYLIKE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|sk-ant-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,})")
_KEY_QUERY = re.compile(r"(key=)[^&\s'\"]+", re.IGNORECASE)


_TRANSPORT_ERRORS = {
    "ClientPayloadError", "TransferEncodingError", "ContentLengthError", "ServerDisconnectedError",
    "ClientConnectorError", "ClientOSError", "ClientConnectionError", "ClientConnectionResetError",
    "RemoteProtocolError", "ReadError", "WriteError", "ConnectError", "NetworkError", "ProtocolError",
    "APIConnectionError", "IncompleteRead",
}


_BILLING_MARKERS = ("credit balance is too low", "no credits remaining", "insufficient_quota",
                    "exceeded your current quota, please check your plan and billing", "billing_hard_limit",
                    "purchase credits", "add credits")


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    out = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***")
    out = _KEY_QUERY.sub(r"\1***", out)
    return _KEYLIKE.sub("***", out)


@dataclass
class ProviderFailure:
    category: ErrorCategory
    message: str
    retryable: bool
    fallback_eligible: bool
    status_code: Optional[int] = None
    detail: str = ""

    def to_error(self, field: Optional[str] = None, extra: Optional[dict] = None) -> NodeExecutionError:
        details = {"status_code": self.status_code, **(extra or {})}
        return NodeExecutionError(self.category, self.message, field=field, retryable=self.retryable,
                                  technical_detail=self.detail[:500] or None, details=details)


def _chain(exc: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    cur: Optional[BaseException] = exc
    while cur is not None and cur not in out and len(out) < 8:
        out.append(cur)
        cur = cur.__cause__ or cur.__context__
    return out


def _status(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify_provider_error(exc: BaseException, provider: str, model: str,
                            secrets: Iterable[str] = ()) -> ProviderFailure:
    """Map any exception raised while calling a model to a ``ProviderFailure``."""
    label = f"{provider}/{model}"
    chain = _chain(exc)
    detail = scrub("; ".join(f"{type(e).__name__}: {e}" for e in chain)[:800], secrets)
    names = " ".join(type(e).__name__.lower() for e in chain)
    text = " ".join(str(e).lower() for e in chain)[:2000]

    if any(isinstance(e, (asyncio.TimeoutError, TimeoutError)) for e in chain) or "timeout" in names:
        return ProviderFailure(ErrorCategory.MODEL_TIMEOUT, f"{label} did not respond before the inference timeout.",
                               True, True, None, detail)

    # Transport failures first: some client errors carry a numeric ``code`` that is NOT an HTTP response status
    # (e.g. aiohttp's TransferEncodingError has code=400 after a connection reset). Found in live verification.
    if any(type(e).__name__ in _TRANSPORT_ERRORS for e in chain) or \
            any(isinstance(e, (ConnectionError, ConnectionResetError, BrokenPipeError)) for e in chain):
        return ProviderFailure(ErrorCategory.MODEL_UNAVAILABLE,
                               f"The connection to {provider} was interrupted ({label}).", True, True, None, detail)

    status = next((s for s in (_status(e) for e in chain) if s is not None), None)
    # Billing / credit problems (OpenAI answers 429 "no credits remaining", Anthropic 400 "credit balance is too
    # low"). Not transient, so never retried; another provider can still serve the request, so fallback-eligible.
    if any(marker in text for marker in _BILLING_MARKERS):
        return ProviderFailure(ErrorCategory.MODEL_UNAVAILABLE,
                               f"The {provider} account has no remaining credit or quota ({label}). Add credits / "
                               "check billing for this API key, or configure a fallback model from another "
                               "provider.", False, True, status, detail)
    if status in (401,) or "authenticationerror" in names or "api key not valid" in text \
            or "invalid x-api-key" in text or "incorrect api key" in text or "api_key_invalid" in text:
        return ProviderFailure(ErrorCategory.MODEL_AUTH, f"{label} rejected the API key.", False, False, status, detail)
    if status == 403 or "permissiondenied" in names:
        return ProviderFailure(ErrorCategory.MODEL_AUTH,
                               f"The API key is not permitted to use {label} (permission denied).",
                               False, False, status, detail)
    if status == 404 or "notfounderror" in names:
        return ProviderFailure(ErrorCategory.UNSUPPORTED_MODEL,
                               f"{label} was not found or is not available to this API key.",
                               False, False, status, detail)
    if status == 429 or "ratelimit" in names or "resource_exhausted" in text:
        return ProviderFailure(ErrorCategory.MODEL_UNAVAILABLE,
                               f"{label} is rate limited or the account quota is exhausted.", True, True, status, detail)
    if status is not None and status >= 500 or "overloaded" in names or "internalservererror" in names \
            or "servererror" in names:
        return ProviderFailure(ErrorCategory.MODEL_UNAVAILABLE,
                               f"{label} is temporarily unavailable (provider error{f' {status}' if status else ''}).",
                               True, True, status, detail)
    if "connection" in names or "connecterror" in names or "networkerror" in names \
            or any(isinstance(e, (ConnectionError, OSError)) for e in chain):
        return ProviderFailure(ErrorCategory.MODEL_UNAVAILABLE, f"Could not connect to {provider}.", True, True,
                               status, detail)
    if status in (400, 409, 413, 422) or "badrequest" in names or "unprocessable" in names:
        reason = "the request exceeds a provider limit" if status == 413 else "the request was rejected"
        return ProviderFailure(ErrorCategory.MODEL_ERROR,
                               f"{label}: {reason} (HTTP {status or 400}). Check the model options, prompt size and "
                               f"output schema.", False, False, status, detail)
    if "refusal" in names or "refus" in text:
        return ProviderFailure(ErrorCategory.INVALID_MODEL_OUTPUT, f"{label} declined to answer this request.",
                               False, False, status, detail)
    return ProviderFailure(ErrorCategory.MODEL_UNAVAILABLE, f"{label} request failed unexpectedly.", False, False,
                           status, detail)
