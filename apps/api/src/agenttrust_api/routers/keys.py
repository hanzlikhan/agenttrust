"""Project API key issuance, listing, revocation, and key-authenticated identity."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AppError, require_admin, require_api_key
from ..models import ApiKey, Project
from ..schemas import (
    ApiKeyListResponse,
    ApiKeyPublic,
    KeyCreateRequest,
    KeyCreateResponse,
    KeyRevokeResponse,
    WhoAmIResponse,
)
from ..security import generate_api_key
from ..util import utcnow

router = APIRouter(tags=["keys"])


def _public(key: ApiKey) -> ApiKeyPublic:
    """Redacted representation: prefix only, never the hash or raw secret."""
    return ApiKeyPublic(
        id=key.id,
        project_id=key.project_id,
        name=key.name,
        key_prefix=key.key_prefix,
        scopes=key.scopes,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@router.post("/keys", status_code=201, response_model=KeyCreateResponse)
def issue_key(
    payload: KeyCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> KeyCreateResponse:
    """Issue a new API key for a project. The raw secret is returned exactly once."""
    project = db.get(Project, payload.project_id)
    if project is None:
        raise AppError("project_not_found", f"Project {payload.project_id} does not exist.", 404)
    raw, prefix, digest = generate_api_key()
    key = ApiKey(
        project_id=project.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=digest,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    return KeyCreateResponse(
        id=key.id,
        project_id=key.project_id,
        name=key.name,
        key_prefix=key.key_prefix,
        api_key=raw,
        scopes=key.scopes,
        expires_at=key.expires_at,
        created_at=key.created_at,
    )


@router.get("/keys", response_model=ApiKeyListResponse)
def list_keys(
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=100),
) -> ApiKeyListResponse:
    """List issued keys with secrets redacted."""
    keys = db.query(ApiKey).order_by(desc(ApiKey.created_at)).limit(limit).all()
    return ApiKeyListResponse(keys=[_public(key) for key in keys])


@router.post("/keys/{key_id}/revoke", response_model=KeyRevokeResponse)
def revoke_key(
    key_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> KeyRevokeResponse:
    """Revoke a key permanently. Revoked keys are rejected on next use."""
    key = db.get(ApiKey, key_id)
    if key is None:
        raise AppError("key_not_found", f"API key {key_id} does not exist.", 404)
    if key.revoked_at is not None:
        raise AppError("key_already_revoked", "This API key is already revoked.", 409)
    key.revoked_at = utcnow()
    db.commit()
    return KeyRevokeResponse(id=key.id, revoked_at=key.revoked_at)


@router.get("/me", response_model=WhoAmIResponse)
def whoami(request: Request, key: ApiKey = Depends(require_api_key)) -> WhoAmIResponse:
    """Return the project identity bound to the presented API key."""
    return WhoAmIResponse(
        project_id=key.project_id,
        project_name=key.project.name,
        key_prefix=key.key_prefix,
        scopes=key.scopes,
    )
