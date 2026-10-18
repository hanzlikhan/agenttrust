"""Alembic environment: run migrations against the configured PostgreSQL database."""

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Make the src-layout package importable when alembic runs from apps/api.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agenttrust_api import models  # noqa: F401  (register table metadata)
from agenttrust_api.config import settings
from agenttrust_api.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Prefer an explicitly configured URL (tests), else the app settings."""
    return config.get_main_option("sqlalchemy.url") or settings.DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(get_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
