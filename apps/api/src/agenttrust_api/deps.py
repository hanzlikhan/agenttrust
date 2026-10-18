"""Authentication and authorization dependencies."""

import secrets

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import ApiKey
from .ratelimit import check_rate_limit
from .security import KEY_PREFIX_CHARS, KEY_SCHEME_PREFIX, verify_api_key
from .util import utcnow


class AppError(Exception):
    """Structured application error, rendered as a JSON error envelope."""

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable


_admin_scheme = HTTPBearer(auto_error=False, description="Admin token for key management")
_api_key_scheme = HTTPBearer(auto_error=False, description="AgentTrust project API key")


def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_scheme),
) -> bool:
    """Require the configured admin bearer token (key issuance / listing / revocation)."""
    if not settings.ADMIN_TOKEN:
        raise AppError(
            "admin_auth_not_configured",
            "Key management is disabled: ADMIN_TOKEN is not set.",
            503,
        )
    presented = credentials.credentials if credentials else ""
    if not secrets.compare_digest(presented, settings.ADMIN_TOKEN):
        raise AppError("admin_forbidden", "Invalid admin token.", 403)
    return True


def _authenticate_api_key(db: Session, raw: str) -> ApiKey:
    """Verify a raw API key value; shared by header and query-param auth."""
    if not raw.startswith(KEY_SCHEME_PREFIX):
        raise AppError("invalid_api_key", "Invalid API key.", 401)
    prefix = raw[: len(KEY_SCHEME_PREFIX) + KEY_PREFIX_CHARS]
    stored = db.query(ApiKey).filter(ApiKey.key_prefix == prefix).first()
    if stored is None or not verify_api_key(raw, stored.key_hash):
        raise AppError("invalid_api_key", "Invalid API key.", 401)
    if stored.revoked_at is not None:
        raise AppError("key_revoked", "This API key has been revoked.", 403)
    if stored.expires_at is not None and stored.expires_at <= utcnow():
        raise AppError("key_expired", "This API key has expired.", 403)
    return stored


def require_api_key(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_api_key_scheme),
) -> ApiKey:
    """Authenticate a project API key from the Authorization header.

    Phase 8 audit DB MEDIUM-3: failed authentications are rate-limited by
    client IP, so unauthenticated floods cannot burn DB lookups
    indefinitely. Successful authentications are unaffected.
    """
    raw = credentials.credentials if credentials else ""
    client_ip = request.client.host if request.client else "unknown"
    try:
        return _authenticate_api_key(db, raw)
    except AppError as exc:
        if exc.status_code == 401:
            # Count the failure against the IP bucket; the bucket is only
            # consulted here, on the failure path.
            if not check_rate_limit(f"rl:auth-fail:{client_ip}", per_minute=30):
                raise AppError(
                    "auth_rate_limited",
                    "Too many failed authentication attempts; slow down.",
                    429,
                ) from exc
        raise


# ---------------------------------------------------------------------------
# Phase 5: API key scopes + rate limiting (M01/M15 security hardening)
# ---------------------------------------------------------------------------

#: Scope required to open runs and ingest telemetry.
SCOPE_AGENT_RUN = "agent:run"
#: Scope required to request policy authorization.
SCOPE_AGENT_AUTHORIZE = "agent:authorize"
#: Scope required to execute through the trusted gateway.
SCOPE_AGENT_EXECUTE = "agent:execute"
#: Scope required to read the approval queue and approval details.
SCOPE_APPROVALS_READ = "approvals:read"
#: Scope required to approve or reject a pending approval.
SCOPE_APPROVALS_DECIDE = "approvals:decide"


def has_scope(key: ApiKey, *required: str) -> bool:
    """True when the key holds any of the required scopes.

    The `"*"` wildcard grants every scope (used by admin-issued and legacy
    seed keys). An empty scope list never grants access.
    """
    scopes = key.scopes or []
    if "*" in scopes:
        return True
    return any(s in scopes for s in required)


def require_scopes(*scopes: str, limit_per_minute: bool = True):  # type: ignore[no-untyped-def]
    """Dependency factory: valid key + required scope(s) + rate limit.

    Raises 403 `insufficient_scope` when the key lacks every listed scope,
    and 429 `rate_limited` (retryable) when the per-key token bucket is
    empty. Buckets are per key id and refill per minute (see ratelimit.py;
    single-process limitation documented in DECISIONS.md).
    """

    def _dep(key: ApiKey = Depends(require_api_key)) -> ApiKey:
        if not has_scope(key, *scopes):
            raise AppError(
                "insufficient_scope",
                f"This API key lacks a required scope (one of: {', '.join(scopes)}).",
                403,
            )
        if limit_per_minute and not check_rate_limit(f"rl:{key.id}"):
            raise AppError(
                "rate_limited",
                "Rate limit exceeded; slow down and retry.",
                429,
                retryable=True,
            )
        return key

    return _dep


def require_reviewer(key: ApiKey = Depends(require_api_key)) -> ApiKey:
    """Authenticate a reviewer credential: valid key + `approvals:decide` scope.

    Separation of duties (requester key != reviewer key) is enforced at the
    decision endpoint, where the approval's requester is known.
    """
    if not has_scope(key, SCOPE_APPROVALS_DECIDE):
        raise AppError(
            "insufficient_scope",
            "This API key cannot decide approvals (missing approvals:decide).",
            403,
        )
    if not check_rate_limit(f"rl:{key.id}"):
        raise AppError(
            "rate_limited",
            "Rate limit exceeded; slow down and retry.",
            429,
            retryable=True,
        )
    return key


def require_api_key_query(
    request: Request,
    db: Session = Depends(get_db),
) -> ApiKey:
    """Authenticate a project API key from the ``api_key`` query parameter.

    EventSource (browser SSE) cannot send Authorization headers, so the
    stream endpoint accepts the key as a query parameter. This is weaker
    than header auth — keys can end up in server access logs and browser
    history — so the endpoint redacts the query string from the request
    scope after reading it, and dashboard session auth (Phase 5/6) will
    replace it. See ADR-027.
    """
    raw = request.query_params.get("api_key", "")
    key = _authenticate_api_key(db, raw)
    # Best-effort: keep the secret out of access logs. Uvicorn builds the
    # logged URL from the scope at response time.
    redacted = [
        (k, "REDACTED" if k == "api_key" else v)
        for k, v in request.query_params.multi_items()
    ]
    request.scope["query_string"] = "&".join(f"{k}={v}" for k, v in redacted).encode()
    return key
