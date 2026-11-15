"""Encrypted credential storage. Decrypted secrets only ever exist inside backend executors."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import ErrorCategory, NodeExecutionError
from app.db.models import Credential

logger = logging.getLogger(__name__)

# Credential type -> required fields, non-secret fields safe to display, secret fields shown masked
# (last 4 characters only) and an optional AI provider the type belongs to.
CREDENTIAL_TYPES: Dict[str, Dict[str, Any]] = {
    "http_bearer": {"label": "HTTP Bearer token", "fields": ["token"], "public": [], "masked": []},
    "http_basic": {"label": "HTTP Basic auth", "fields": ["username", "password"], "public": ["username"],
                   "masked": []},
    "http_header": {"label": "HTTP header", "fields": ["name", "value"], "public": ["name"], "masked": []},
    # AI model provider API keys (Milestone 2). Used only by AI Generate / AI Agent nodes.
    "openai_api_key": {"label": "OpenAI API key", "fields": ["api_key"], "public": [], "masked": ["api_key"],
                       "provider": "openai"},
    "anthropic_api_key": {"label": "Anthropic API key", "fields": ["api_key"], "public": [], "masked": ["api_key"],
                          "provider": "anthropic"},
    "gemini_api_key": {"label": "Google Gemini API key", "fields": ["api_key"], "public": [], "masked": ["api_key"],
                       "provider": "gemini"},
}

PROVIDER_CREDENTIAL_TYPE: Dict[str, str] = {
    spec["provider"]: name for name, spec in CREDENTIAL_TYPES.items() if spec.get("provider")
}


def mask_secret(value: str) -> str:
    """'sk-abc...wxyz' -> '••••wxyz' (never more than the last 4 characters)."""
    value = str(value or "")
    return "••••" + value[-4:] if len(value) >= 12 else "••••"


class CredentialError(ValueError):
    pass


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if key:
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key.") from exc
    if settings.is_production:
        raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY must be set when APP_ENV=production.")
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.effective_jwt_secret.encode()).digest())
    return Fernet(derived)


def validate_credential_data(cred_type: str, data: Dict[str, Any]) -> Dict[str, str]:
    spec = CREDENTIAL_TYPES.get(cred_type)
    if spec is None:
        raise CredentialError(f"Unsupported credential type '{cred_type}'. Use one of: {', '.join(CREDENTIAL_TYPES)}.")
    clean: Dict[str, str] = {}
    for field in spec["fields"]:
        value = data.get(field)
        if value is None or str(value) == "":
            raise CredentialError(f"Credential field '{field}' is required for type '{cred_type}'.")
        clean[field] = str(value)
    return clean


def _decrypt(cred: Credential) -> Dict[str, Any]:
    return json.loads(_fernet().decrypt(cred.encrypted_data.encode()).decode())


def public_view(cred: Credential) -> Dict[str, Any]:
    """Metadata safe to return to the browser (never secrets; API keys only as a masked suffix)."""
    hints: Dict[str, str] = {}
    spec = CREDENTIAL_TYPES.get(cred.type, {"public": [], "masked": []})
    if spec.get("public") or spec.get("masked"):
        try:
            data = _decrypt(cred)
            hints = {k: str(data.get(k, "")) for k in spec.get("public", [])}
            hints.update({k: mask_secret(data.get(k, "")) for k in spec.get("masked", [])})
        except (InvalidToken, ValueError):
            hints = {}
    return {"id": cred.id, "type": cred.type, "name": cred.name, "hints": hints,
            "provider": spec.get("provider"),
            "created_at": cred.created_at.isoformat() if cred.created_at else None,
            "updated_at": cred.updated_at.isoformat() if cred.updated_at else None}


async def update_credential(session: AsyncSession, cred: Credential, name: Optional[str],
                            data: Optional[Dict[str, Any]]) -> Credential:
    """Rename and/or replace secret fields. Omitted or empty fields keep their stored value."""
    if name is not None and name.strip():
        cred.name = name.strip()
    if data:
        try:
            current = _decrypt(cred)
        except (InvalidToken, ValueError) as exc:
            raise CredentialError("The stored secret cannot be decrypted; delete and re-create the credential.") from exc
        merged = {**current, **{k: v for k, v in data.items() if v not in (None, "")}}
        clean = validate_credential_data(cred.type, merged)
        cred.encrypted_data = _fernet().encrypt(json.dumps(clean).encode()).decode()
    from app.db.models import utcnow
    cred.updated_at = utcnow()
    await session.commit()
    await session.refresh(cred)
    return cred


def decrypt_owned(cred: Credential) -> Dict[str, Any]:
    """Decrypt a credential the caller has already verified the user owns (backend-only use)."""
    return _decrypt(cred)


async def create_credential(session: AsyncSession, user_id: str, cred_type: str, name: str,
                            data: Dict[str, Any]) -> Credential:
    clean = validate_credential_data(cred_type, data)
    token = _fernet().encrypt(json.dumps(clean).encode()).decode()
    cred = Credential(user_id=user_id, type=cred_type, name=name.strip() or cred_type, encrypted_data=token)
    session.add(cred)
    await session.commit()
    await session.refresh(cred)
    return cred


async def list_credentials(session: AsyncSession, user_id: str) -> List[Credential]:
    rows = await session.execute(select(Credential).where(Credential.user_id == user_id).order_by(Credential.created_at))
    return list(rows.scalars())


async def get_owned_credential(session: AsyncSession, user_id: str, credential_id: str) -> Optional[Credential]:
    row = await session.execute(
        select(Credential).where(Credential.id == credential_id, Credential.user_id == user_id)
    )
    return row.scalar_one_or_none()


async def credential_ids_for_user(session: AsyncSession, user_id: str) -> set[str]:
    rows = await session.execute(select(Credential.id).where(Credential.user_id == user_id))
    return set(rows.scalars())


class DbCredentialAccessor:
    """Executor-facing accessor scoped to a single user."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], user_id: str) -> None:
        self._sm = sessionmaker
        self._user_id = user_id

    async def get(self, credential_id: str, expected_types: Optional[List[str]] = None,
                  field: str = "auth.credential_id") -> Dict[str, Any]:
        async with self._sm() as session:
            cred = await get_owned_credential(session, self._user_id, credential_id)
        if cred is None:
            raise NodeExecutionError(
                ErrorCategory.MISSING_CREDENTIALS,
                "The selected credential does not exist or does not belong to you.",
                field=field,
            )
        if expected_types and cred.type not in expected_types:
            raise NodeExecutionError(
                ErrorCategory.MISSING_CREDENTIALS,
                f"Credential '{cred.name}' has type '{cred.type}', expected {' or '.join(expected_types)}.",
                field=field,
            )
        try:
            return _decrypt(cred)
        except InvalidToken as exc:
            raise NodeExecutionError(
                ErrorCategory.AUTH_FAILURE,
                f"Credential '{cred.name}' cannot be decrypted (the encryption key changed?). Re-create it.",
                field=field,
            ) from exc
