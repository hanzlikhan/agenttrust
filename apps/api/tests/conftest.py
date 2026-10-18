"""Test configuration: real PostgreSQL test database, migrated via Alembic.

Environment variables are set BEFORE importing any application module so the
module-level settings pick up the test configuration.
"""

import os
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql+psycopg://agenttrust:agenttrust@localhost:5432/agenttrust_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["AGENTTRUST_ENV"] = "test"

import uuid  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from agenttrust_api import models  # noqa: E402
from agenttrust_api.db import get_db  # noqa: E402
from agenttrust_api.main import create_app  # noqa: E402
from agenttrust_api.util import utcnow  # noqa: E402
from alembic import command  # noqa: E402


def _libpq_url(url: str) -> str:
    """Convert a SQLAlchemy URL to libpq conninfo format for raw psycopg use."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _ensure_database(url: str) -> None:
    dbname = url.rsplit("/", 1)[-1]
    admin_url = _libpq_url(url.rsplit("/", 1)[0] + "/postgres")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')


def _alembic_cfg(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def migrated_db_url() -> str:
    _ensure_database(TEST_DATABASE_URL)
    cfg = _alembic_cfg(TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return TEST_DATABASE_URL


@pytest.fixture()
def db_session(migrated_db_url: str):
    """A transactional session with a seeded owner + project; rolled back after each test."""
    engine = create_engine(migrated_db_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    connection = engine.connect()
    transaction = connection.begin()
    session = factory(bind=connection)

    owner = models.User(username=f"owner-{uuid.uuid4().hex[:8]}")
    session.add(owner)
    session.flush()
    project = models.Project(name="demo", owner_id=owner.id)
    session.add(project)
    session.flush()
    session.add(models.Membership(user_id=owner.id, project_id=project.id, role="owner"))
    session.flush()

    yield session, project

    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture()
def client(db_session):
    session, _project = db_session
    app = create_app()

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def project_id(db_session) -> uuid.UUID:
    _session, project = db_session
    return project.id


@pytest.fixture()
def admin_headers() -> dict:
    return {"Authorization": "Bearer test-admin-token"}


# ---------------------------------------------------------------------------
# Phase 3 shared fixtures: seeded tool/policy/orders + API key + run.
# ---------------------------------------------------------------------------

_V1_RULES = {
    "tool_name": "refund_payment",
    "currency": "USD",
    "auto_approve_max_minor": 10000,
    "review_max_minor": 50000,
}


@pytest.fixture()
def key_headers(client, admin_headers, project_id):
    """Issue an API key; returns (headers, raw_key)."""
    resp = client.post(
        "/api/v1/keys",
        json={"project_id": str(project_id), "name": "test-key", "scopes": ["*"]},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    raw = resp.json()["api_key"]
    return {"Authorization": f"Bearer {raw}"}, raw


@pytest.fixture()
def orders(db_session):
    session, _ = db_session
    rows = [
        ("ORD-100", 40000, 40000, "USD", True),
        ("ORD-200", 100000, 100000, "USD", False),
        ("ORD-300", 20000, 5000, "USD", True),
    ]
    for ref, total, remaining, currency, eligible in rows:
        session.add(
            models.MockOrder(
                order_ref=ref,
                total_minor=total,
                refundable_remaining_minor=remaining,
                currency=currency,
                eligible=eligible,
                status="open",
                created_at=utcnow(),
            )
        )
    session.flush()


@pytest.fixture()
def policy_stack(client, admin_headers, project_id, orders):
    """Register refund_payment v1 and activate refund-policy v1."""
    from agenttrust_api.policy.rules import REFUND_PAYMENT_SCHEMA

    resp = client.post(
        "/api/v1/tools",
        json={
            "project_id": str(project_id),
            "slug": "refund_payment",
            "version": 1,
            "schema_json": REFUND_PAYMENT_SCHEMA,
            "risk_class": "high_impact",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    resp = client.post(
        "/api/v1/policies",
        json={
            "project_id": str(project_id),
            "name": "refund-policy",
            "rules_json": _V1_RULES,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    policy_id = resp.json()["id"]
    resp = client.post(f"/api/v1/policies/{policy_id}/activate", headers=admin_headers)
    assert resp.status_code == 200, resp.text


@pytest.fixture()
def run_id(client, key_headers):
    headers, _raw = key_headers
    resp = client.post(
        "/api/v1/runs",
        json={"agent_name": "test-agent", "agent_version": "0.1.0"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["run_id"]
