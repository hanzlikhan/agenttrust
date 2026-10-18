"""Policy authoring, versioning, activation, and simulation (M05).

Versions are immutable once activated: every edit creates a new version row.
`/policies/simulate` is non-mutating — it previews a decision without writing
anything to the database.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AppError, require_admin, require_api_key
from ..models import ApiKey, Policy, PolicyVersion, Project
from ..policy.rules import RefundPolicyConfig
from ..policy.service import simulate_decision
from ..schemas import (
    PolicyActivateResponse,
    PolicyCreateRequest,
    PolicyListResponse,
    PolicyResponse,
    PolicyVersionResponse,
    SimulateRequest,
    SimulateResponse,
)
from ..util import utcnow

router = APIRouter(tags=["policies"])


def _public_version(version: PolicyVersion) -> PolicyVersionResponse:
    return PolicyVersionResponse(
        id=version.id,
        version=version.version,
        rules_json=version.rules_json,
        created_by=version.created_by,
        activated_at=version.activated_at,
        created_at=version.created_at,
    )


def _public(policy: Policy) -> PolicyResponse:
    return PolicyResponse(
        id=policy.id,
        project_id=policy.project_id,
        name=policy.name,
        active_version_id=policy.active_version_id,
        versions=[_public_version(v) for v in policy.versions],
        created_at=policy.created_at,
    )


@router.post("/policies", status_code=201, response_model=PolicyResponse)
def create_policy_draft(
    payload: PolicyCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> PolicyResponse:
    """Create a new draft version of a policy's rules.

    The rules are validated against the refund policy config schema on receipt;
    the version is a draft (not active) until explicitly activated.
    """
    project = db.get(Project, payload.project_id)
    if project is None:
        raise AppError(
            "project_not_found", f"Project {payload.project_id} does not exist.", 404
        )
    try:
        RefundPolicyConfig.model_validate(payload.rules_json)
    except ValidationError as exc:
        raise AppError(
            "invalid_policy_rules",
            f"rules_json failed policy config validation: {exc.errors()[0]['msg']}",
            422,
        ) from exc

    policy = (
        db.query(Policy)
        .filter(Policy.project_id == project.id, Policy.name == payload.name)
        .first()
    )
    if policy is None:
        policy = Policy(
            project_id=project.id, name=payload.name, created_at=utcnow()
        )
        db.add(policy)
        db.flush()

    next_version = max((v.version for v in policy.versions), default=0) + 1
    version = PolicyVersion(
        policy_id=policy.id,
        version=next_version,
        rules_json=payload.rules_json,
        created_by="admin",
        activated_at=None,
        created_at=utcnow(),
    )
    db.add(version)
    db.commit()
    db.refresh(policy)
    return _public(policy)


@router.post("/policies/{policy_id}/activate", response_model=PolicyActivateResponse)
def activate_policy(
    policy_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> PolicyActivateResponse:
    """Activate the latest draft version. Activated versions are never mutated."""
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise AppError("policy_not_found", f"Policy {policy_id} does not exist.", 404)
    if not policy.versions:
        raise AppError("no_policy_version", "This policy has no versions to activate.", 409)
    latest = max(policy.versions, key=lambda v: v.version)
    if latest.activated_at is not None:
        raise AppError(
            "no_draft_version",
            f"Version {latest.version} is already active; create a new draft to change rules.",
            409,
        )
    latest.activated_at = utcnow()
    policy.active_version_id = latest.id
    db.commit()
    return PolicyActivateResponse(
        id=policy.id,
        name=policy.name,
        active_version_id=latest.id,
        activated_version=latest.version,
        activated_at=latest.activated_at,
    )


@router.get("/policies", response_model=PolicyListResponse)
def list_policies(
    request: Request,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_api_key),
) -> PolicyListResponse:
    """List this project's policies with their versions."""
    policies = (
        db.query(Policy).filter(Policy.project_id == key.project_id).order_by(Policy.name).all()
    )
    return PolicyListResponse(policies=[_public(policy) for policy in policies])


@router.post("/policies/simulate", response_model=SimulateResponse)
def simulate_policy(
    payload: SimulateRequest,
    request: Request,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
) -> SimulateResponse:
    """Preview the decision a policy version would make. Writes nothing."""
    project = db.get(Project, payload.project_id)
    if project is None:
        raise AppError(
            "project_not_found", f"Project {payload.project_id} does not exist.", 404
        )
    result = simulate_decision(
        db=db,
        project_id=project.id,
        tool_name=payload.tool_name,
        arguments=payload.arguments,
    )
    return SimulateResponse(
        outcome=result.outcome,
        reason_code=result.reason_code,
        policy_version=result.policy_version,
        evaluated_with_draft=result.evaluated_with_draft,
        explanation=result.explanation,
    )
