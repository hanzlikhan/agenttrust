"""Phase 5 schema: durable human approval queue (M10).

New ``approvals`` table with an explicit state machine
(PENDING -> APPROVED | REJECTED | EXPIRED), optimistic-concurrency
``row_version``, and an expiry timestamp. One active approval per tool call.

Downgrade drops the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_calls.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "requester_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("state", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("reason", sa.String(256), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_approvals_state_expires", "approvals", ["state", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_state_expires", table_name="approvals")
    op.drop_table("approvals")
