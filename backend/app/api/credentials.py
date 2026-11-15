"""User-scoped credential management. Secrets are write-only: they are never returned."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User
from app.db.session import get_session
from app.schemas.api import CredentialCreate, CredentialOut, CredentialTestResult, CredentialUpdate
from app.services import credentials as svc

router = APIRouter(prefix="/api/credentials", tags=["Credentials"])


@router.get("/types")
async def credential_types() -> Dict[str, List[str]]:
    return {name: spec["fields"] for name, spec in svc.CREDENTIAL_TYPES.items()}


@router.get("/type-specs")
async def credential_type_specs() -> List[Dict[str, Any]]:
    """Credential types with labels, required fields, which fields are secret, and the AI provider (if any)."""
    return [{"type": name, "label": spec.get("label", name), "fields": spec["fields"],
             "secret_fields": [f for f in spec["fields"] if f not in spec.get("public", [])],
             "provider": spec.get("provider"), "testable": bool(spec.get("provider"))}
            for name, spec in svc.CREDENTIAL_TYPES.items()]


@router.get("", response_model=List[CredentialOut])
async def list_credentials(user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session)) -> List[CredentialOut]:
    return [CredentialOut(**svc.public_view(c)) for c in await svc.list_credentials(session, user.id)]


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
async def create_credential(payload: CredentialCreate, user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session)) -> CredentialOut:
    try:
        cred = await svc.create_credential(session, user.id, payload.type, payload.name, payload.data)
    except svc.CredentialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CredentialOut(**svc.public_view(cred))


@router.put("/{credential_id}", response_model=CredentialOut)
async def update_credential(credential_id: str, payload: CredentialUpdate, user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session)) -> CredentialOut:
    """Rename a credential and/or replace its secret. Secrets stay write-only."""
    cred = await svc.get_owned_credential(session, user.id, credential_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    try:
        cred = await svc.update_credential(session, cred, payload.name, payload.data)
    except svc.CredentialError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CredentialOut(**svc.public_view(cred))


@router.post("/{credential_id}/test", response_model=CredentialTestResult)
async def test_credential(credential_id: str, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)) -> CredentialTestResult:
    """Real connection test against the provider API (lists models; no inference, no tokens billed)."""
    from app.ai.providers import test_connection

    cred = await svc.get_owned_credential(session, user.id, credential_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    provider = svc.CREDENTIAL_TYPES.get(cred.type, {}).get("provider")
    if not provider:
        raise HTTPException(status_code=400, detail=f"Connection tests are not available for '{cred.type}' "
                                                    "credentials; they are verified when an HTTP Request uses them.")
    result = await test_connection(provider, str(svc.decrypt_owned(cred).get("api_key", "")))
    return CredentialTestResult(ok=result.ok, message=result.message, provider=provider, category=result.category,
                                models_available=result.models_available or [])


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(credential_id: str, user: User = Depends(get_current_user),
                            session: AsyncSession = Depends(get_session)) -> Response:
    cred = await svc.get_owned_credential(session, user.id, credential_id)
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    await session.delete(cred)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
