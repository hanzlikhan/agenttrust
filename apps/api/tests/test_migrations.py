"""Migration chain tests against a dedicated scratch database."""

import os
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

API_DIR = Path(__file__).resolve().parent.parent
MIG_DATABASE_URL = os.environ.get(
    "DATABASE_URL_MIGTEST",
    "postgresql+psycopg://agenttrust:agenttrust@localhost:5432/agenttrust_migtest",
)
EXPECTED_TABLES = {
    "users",
    "projects",
    "memberships",
    "api_keys",
    # Phase 2: policy engine
    "agents",
    "agent_runs",
    "tool_definitions",
    "tool_calls",
    "policies",
    "policy_versions",
    "policy_decisions",
    "mock_orders",
    # Phase 3: trusted gateway + events
    "execution_grants",
    "tool_executions",
    "events",
    "outbox",
    # Phase 5: human approvals
    "approvals",
}


def _cfg() -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", MIG_DATABASE_URL)
    return cfg


def _libpq_url(url: str) -> str:
    """Convert a SQLAlchemy URL to libpq conninfo format for raw psycopg use."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def scratch_db():
    dbname = MIG_DATABASE_URL.rsplit("/", 1)[-1]
    admin_url = _libpq_url(MIG_DATABASE_URL.rsplit("/", 1)[0] + "/postgres")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        conn.execute(f'CREATE DATABASE "{dbname}"')
    yield MIG_DATABASE_URL
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')


def test_upgrade_head_creates_expected_tables(scratch_db):
    command.upgrade(_cfg(), "head")
    engine = create_engine(scratch_db)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert EXPECTED_TABLES <= tables


def test_downgrade_base_removes_tables(scratch_db):
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), "base")
    engine = create_engine(scratch_db)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert EXPECTED_TABLES.isdisjoint(tables)
