"""Classification of Gemini designer/reviewer failures into user-facing errors.

The raw exceptions from urllib (REST path) and google-genai (SDK path) are
technical and may even contain the API key (the REST URL carries ``?key=``).
``classify_llm_error`` turns them into a stable category, a short message, a
concrete suggestion, and whether trying another configured model can help.
Every message passes through ``scrub_secrets`` before it leaves this module.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import urllib.error
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional

_KEY_QUERY_RE = re.compile(r"(key=)[^&\s'\"]+", re.IGNORECASE)
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")


@dataclass
class LLMErrorInfo:
    category: str  # see CATEGORIES
    message: str
    suggestion: str
    retry_other_models: bool  # can another configured model plausibly succeed?
    status_code: Optional[int] = None
    model: Optional[str] = None

    def to_detail(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("retry_other_models", None)
        return data


CATEGORIES = (
    "missing_api_key", "invalid_api_key", "permission_denied", "quota_exceeded", "timeout",
    "network", "model_not_found", "bad_request", "provider_unavailable", "empty_response", "unknown",
)

# Higher = more useful to show the user when several models failed differently.
_PRIORITY = {
    "invalid_api_key": 9, "missing_api_key": 9, "permission_denied": 8, "quota_exceeded": 7,
    "network": 6, "timeout": 5, "provider_unavailable": 4, "model_not_found": 3, "bad_request": 3,
    "empty_response": 2, "unknown": 0,
}


class GeminiHTTPError(RuntimeError):
    """HTTP error from the Gemini REST endpoint with the parsed Google error body."""

    def __init__(self, status_code: int, api_status: str = "", api_message: str = "") -> None:
        super().__init__(f"Gemini HTTP {status_code} {api_status}: {api_message}".strip())
        self.status_code = status_code
        self.api_status = api_status or ""
        self.api_message = api_message or ""

    @classmethod
    def from_http_error(cls, exc: urllib.error.HTTPError) -> GeminiHTTPError:
        status, message = "", ""
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
            err = body.get("error", {}) if isinstance(body, dict) else {}
            status, message = str(err.get("status") or ""), str(err.get("message") or "")
        except Exception:  # body is optional diagnostic data only
            pass
        return cls(exc.code, status, message)


def scrub_secrets(text: str, secrets: Iterable[Optional[str]] = ()) -> str:
    """Remove API keys (explicit values, ``key=...`` query params, Google key shapes)."""
    out = str(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***")
    out = _KEY_QUERY_RE.sub(r"\1***", out)
    return _GOOGLE_KEY_RE.sub("***", out)


def _from_status(code: int, api_status: str, api_message: str, model: Optional[str]) -> LLMErrorInfo:
    text = f"{api_status} {api_message}".lower()
    where = f" for model '{model}'" if model else ""
    if "api_key_invalid" in text or "api key not valid" in text or "api key expired" in text or code == 401:
        return LLMErrorInfo("invalid_api_key", "Gemini rejected the API key.",
                            "Check GEMINI_API_KEY in backend/.env (create a key in Google AI Studio) and "
                            "restart the backend.", False, code, model)
    if code == 403 or api_status == "PERMISSION_DENIED":
        return LLMErrorInfo("permission_denied", f"The Gemini API key is not allowed to use this API{where}.",
                            "Enable the Generative Language API for the key's project, or check the key's "
                            "API restrictions.", False, code, model)
    if code == 429 or api_status == "RESOURCE_EXHAUSTED":
        return LLMErrorInfo("quota_exceeded", f"Gemini quota or rate limit exceeded{where}.",
                            "Wait a minute and try again, or check your quota in Google AI Studio.",
                            True, code, model)
    if code == 404 or api_status == "NOT_FOUND":
        name = f" '{model}'" if model else ""
        return LLMErrorInfo("model_not_found", f"Gemini model{name} was not found or is not available "
                            "to this key.", "Check GEMINI_MODEL / GEMINI_FALLBACK_MODEL / "
                            "GEMINI_REVIEWER_MODEL in backend/.env.", True, code, model)
    if code in (408, 504) or api_status == "DEADLINE_EXCEEDED":
        return LLMErrorInfo("timeout", f"Gemini took too long to respond{where}.",
                            "Try again; shorter prompts respond faster.", True, code, model)
    if code >= 500:
        return LLMErrorInfo("provider_unavailable", f"Gemini is temporarily unavailable{where} (HTTP {code}).",
                            "Try again in a few moments.", True, code, model)
    return LLMErrorInfo("bad_request", f"Gemini rejected the request{where} (HTTP {code}).",
                        "Try again or rephrase the request. If it keeps failing, check the configured "
                        "model names.", True, code, model)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    name = type(exc).__name__.lower()
    return "timeout" in name


def classify_llm_error(exc: BaseException, model: Optional[str] = None) -> LLMErrorInfo:
    """Map any designer/reviewer exception to an ``LLMErrorInfo`` (never raises)."""
    from app.services.llm_service import LLMConfigurationError, LLMGenerationError  # local: avoid cycle

    if isinstance(exc, LLMConfigurationError):
        return LLMErrorInfo("missing_api_key", "The AI designer is not configured: GEMINI_API_KEY is missing.",
                            "Add GEMINI_API_KEY to backend/.env and restart the backend.", False, None, model)
    if isinstance(exc, LLMGenerationError) and exc.info is not None:
        return exc.info
    if isinstance(exc, GeminiHTTPError):
        return _from_status(exc.status_code, exc.api_status, exc.api_message, model)
    if isinstance(exc, urllib.error.HTTPError):
        return _from_status(exc.code, "", "", model)

    # google-genai SDK errors expose .code / .status / .message
    code = getattr(exc, "code", None)
    if isinstance(code, int) and 100 <= code < 600 and type(exc).__module__.startswith("google"):
        return _from_status(code, str(getattr(exc, "status", "") or ""), str(getattr(exc, "message", "") or ""),
                            model)

    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if _is_timeout(exc) or (isinstance(reason, BaseException) and _is_timeout(reason)):
        return LLMErrorInfo("timeout", "Gemini did not respond in time.",
                            "Try again. If this keeps happening, check your network connection.", True, None, model)
    if isinstance(reason, socket.gaierror):
        return LLMErrorInfo("network", "Could not reach Gemini: the DNS lookup for "
                            "generativelanguage.googleapis.com failed.",
                            "Check your internet connection, VPN or proxy settings.", False, None, model)
    if isinstance(reason, ssl.SSLError):
        return LLMErrorInfo("network", "Could not establish a secure connection to Gemini (TLS error).",
                            "Check proxy/antivirus HTTPS inspection or system certificates.", False, None, model)
    if isinstance(reason, (ConnectionError, OSError)) or type(exc).__name__ in {"ConnectError", "NetworkError",
                                                                                 "RemoteProtocolError"}:
        return LLMErrorInfo("network", "Could not connect to Gemini.",
                            "Check your internet connection, firewall, VPN or proxy settings.", False, None, model)
    if isinstance(exc, LLMGenerationError):
        return LLMErrorInfo("empty_response", scrub_secrets(str(exc)),
                            "Try again; the model returned no usable content.", True, None, model)
    return LLMErrorInfo("unknown", "The AI designer request failed unexpectedly.",
                        "Try again. If it keeps failing, check the backend logs.", True, None, model)


def most_relevant(infos: Iterable[LLMErrorInfo]) -> Optional[LLMErrorInfo]:
    """Pick the most informative error when several models/paths failed."""
    best: Optional[LLMErrorInfo] = None
    for info in infos:
        if best is None or _PRIORITY.get(info.category, 0) > _PRIORITY.get(best.category, 0):
            best = info
    return best
