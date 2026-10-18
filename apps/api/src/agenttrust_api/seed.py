"""Seed a local demo project and print one API key (copy-once).

Usage:
    PYTHONPATH=src python -m agenttrust_api.seed

The raw key is printed exactly once, on first creation. Re-running the seed
does not re-issue or re-print an existing key. Tool, policy, and mock-order
seeding is idempotent and runs on every invocation.
"""

import sys

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import (
    ApiKey,
    Membership,
    MockOrder,
    Policy,
    PolicyVersion,
    Project,
    ToolDefinition,
    User,
)
from .policy.rules import REFUND_PAYMENT_SCHEMA, RefundPolicyConfig
from .security import generate_api_key
from .util import utcnow

MOCK_ORDERS = [
    # (order_ref, total_minor, remaining_minor, currency, eligible)
    ("ORD-100", 40000, 40000, "USD", True),  # eligible, $400.00 remaining
    ("ORD-200", 100000, 100000, "USD", False),  # ineligible
    ("ORD-300", 20000, 5000, "USD", True),  # eligible, $50.00 remaining
]


def seed_policy_stack(session: Session, project: Project) -> None:
    """Idempotently register the refund tool, its policy, and mock orders."""
    tool = (
        session.query(ToolDefinition)
        .filter(
            ToolDefinition.project_id == project.id,
            ToolDefinition.slug == "refund_payment",
            ToolDefinition.version == 1,
        )
        .first()
    )
    if tool is None:
        session.add(
            ToolDefinition(
                project_id=project.id,
                slug="refund_payment",
                version=1,
                schema_json=REFUND_PAYMENT_SCHEMA,
                risk_class="high_impact",
                created_at=utcnow(),
            )
        )

    policy = (
        session.query(Policy)
        .filter(Policy.project_id == project.id, Policy.name == "refund-policy")
        .first()
    )
    if policy is None:
        policy = Policy(project_id=project.id, name="refund-policy", created_at=utcnow())
        session.add(policy)
        session.flush()
    if not policy.versions:
        rules = RefundPolicyConfig().model_dump()
        version = PolicyVersion(
            policy_id=policy.id,
            version=1,
            rules_json=rules,
            created_by="seed",
            activated_at=utcnow(),
            created_at=utcnow(),
        )
        session.add(version)
        session.flush()
        policy.active_version_id = version.id

    for order_ref, total, remaining, currency, eligible in MOCK_ORDERS:
        exists = (
            session.query(MockOrder).filter(MockOrder.order_ref == order_ref).first()
        )
        if exists is None:
            session.add(
                MockOrder(
                    order_ref=order_ref,
                    total_minor=total,
                    refundable_remaining_minor=remaining,
                    currency=currency,
                    eligible=eligible,
                    status="open",
                    created_at=utcnow(),
                )
            )
    session.flush()


def main() -> int:
    session = SessionLocal()
    try:
        session.query(User).first()
    except OperationalError:
        print(
            "error: database tables are missing — run `alembic upgrade head` first.",
            file=sys.stderr,
        )
        return 1

    user = session.query(User).filter(User.username == "owner").first()
    if user is None:
        user = User(username="owner")
        session.add(user)
        session.flush()

    project = (
        session.query(Project)
        .filter(Project.owner_id == user.id, Project.name == "demo")
        .first()
    )
    if project is None:
        project = Project(name="demo", owner_id=user.id)
        session.add(project)
        session.flush()

    membership = (
        session.query(Membership)
        .filter(Membership.user_id == user.id, Membership.project_id == project.id)
        .first()
    )
    if membership is None:
        session.add(Membership(user_id=user.id, project_id=project.id, role="owner"))
    session.flush()

    seed_policy_stack(session, project)
    session.commit()

    active = (
        session.query(ApiKey)
        .filter(ApiKey.project_id == project.id, ApiKey.revoked_at.is_(None))
        .first()
    )
    session.commit()

    if active is not None:
        print(
            f"demo project already has an active key (prefix {active.key_prefix}); "
            "not re-issuing."
        )
        print(f"project_id={project.id}")
    else:
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(
                project_id=project.id,
                name="demo-seed",
                key_prefix=prefix,
                key_hash=digest,
                scopes=["*"],
            )
        )
        session.commit()
        print("Seeded demo project. COPY THIS API KEY NOW — it will never be shown again:")
        print(raw)
        print(f"project_id={project.id}")

    # Phase 5: a reviewer credential with only approval scopes, demonstrating
    # separation of duties (it cannot authorize or execute tool calls).
    reviewer = session.query(User).filter(User.username == "reviewer").first()
    if reviewer is None:
        reviewer = User(username="reviewer")
        session.add(reviewer)
        session.flush()
        session.add(
            Membership(user_id=reviewer.id, project_id=project.id, role="reviewer")
        )
        session.flush()

    reviewer_key = (
        session.query(ApiKey)
        .filter(
            ApiKey.project_id == project.id,
            ApiKey.name == "demo-reviewer",
            ApiKey.revoked_at.is_(None),
        )
        .first()
    )
    if reviewer_key is None:
        raw, prefix, digest = generate_api_key()
        session.add(
            ApiKey(
                project_id=project.id,
                name="demo-reviewer",
                key_prefix=prefix,
                key_hash=digest,
                scopes=["approvals:read", "approvals:decide"],
            )
        )
        session.commit()
        print(
            "Seeded reviewer key (approvals:read, approvals:decide). "
            "COPY THIS KEY NOW — it will never be shown again:"
        )
        print(raw)
    else:
        session.commit()
        print(
            f"demo project already has a reviewer key (prefix {reviewer_key.key_prefix}); "
            "not re-issuing."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
