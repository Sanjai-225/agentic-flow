"""Redaction and size-capping for anything persisted or returned to the browser."""

from __future__ import annotations

import json
import re
from typing import Any

REDACTED = "***redacted***"
_SENSITIVE_KEY = re.compile(
    r"(authorization|cookie|passw(or)?d|secret|token|api[-_]?key|private[-_]?key|access[-_]?key|client[-_]?secret)",
    re.IGNORECASE,
)
_NOT_SENSITIVE = {"credential_id", "max_tokens", "token_count"}
MAX_STORED_BYTES = 1_000_000
PREVIEW_CHARS = 20_000


def is_sensitive_key(key: str) -> bool:
    return key.lower() not in _NOT_SENSITIVE and bool(_SENSITIVE_KEY.search(key))


def redact(value: Any) -> Any:
    """Recursively replace values of sensitive-looking keys."""
    if isinstance(value, dict):
        return {k: (REDACTED if isinstance(k, str) and is_sensitive_key(k) and v not in (None, "")
                    else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def storable(value: Any) -> Any:
    """Return a JSON-serialisable copy, truncated to a preview when very large."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = json.dumps(str(value))
    if len(text.encode("utf-8", errors="ignore")) > MAX_STORED_BYTES:
        return {"_truncated": True, "size_bytes": len(text), "preview": text[:PREVIEW_CHARS]}
    return json.loads(text)


def redact_text(text: str, secrets: list[str] | None = None) -> str:
    out = text
    for s in secrets or []:
        if s and len(s) >= 4:
            out = out.replace(s, REDACTED)
    return out


def scrub_secrets_in(value: Any, secrets: set[str] | list[str] | None) -> Any:
    """Recursively replace literal secret values inside strings (keys, nested dicts and lists)."""
    usable = [s for s in (secrets or []) if s and len(s) >= 4]
    if not usable:
        return value
    if isinstance(value, str):
        return redact_text(value, usable)
    if isinstance(value, dict):
        return {(redact_text(k, usable) if isinstance(k, str) else k): scrub_secrets_in(v, usable)
                for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_secrets_in(v, usable) for v in value]
    return value
