"""Phase 4 schema: per-project monotonic event sequence (M08 realtime).

New table ``project_event_seq`` (one counter row per project) and a new
``events.project_seq`` column assigned atomically by ``record_event`` via a
row lock on the counter. Existing events are backfilled per project ordered
by (received_at, seq) so the SSE ``Last-Event-ID`` cursor is gap-free from
the start. The old database-wide bigserial ``events.seq`` is kept for
diagnostics.

Downgrade removes the column and the counter table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_event_seq",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("next_seq", sa.BigInteger(), nullable=False, server_default="1"),
    )

    op.add_column("events", sa.Column("project_seq", sa.BigInteger(), nullable=True))

    # Backfill: number each project's existing events 1..N in receipt order,
    # then set each counter to N+1 (1 for projects with no events yet).
    op.execute(
        sa.text(
            """
            WITH numbered AS (
                SELECT event_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY project_id ORDER BY received_at, seq
                       ) AS pseq
                FROM events
            )
            UPDATE events e
            SET project_seq = numbered.pseq
            FROM numbered
            WHERE e.event_id = numbered.event_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO project_event_seq (project_id, next_seq)
            SELECT p.id, COALESCE(m.max_seq, 0) + 1
            FROM projects p
            LEFT JOIN (
                SELECT project_id, MAX(project_seq) AS max_seq
                FROM events
                GROUP BY project_id
            ) m ON m.project_id = p.id
            ON CONFLICT (project_id) DO NOTHING
            """
        )
    )

    op.alter_column("events", "project_seq", existing_type=sa.BigInteger(), nullable=False)
    op.create_index(
        "ix_events_project_project_seq", "events", ["project_id", "project_seq"]
    )


def downgrade() -> None:
    op.drop_index("ix_events_project_project_seq", table_name="events")
    op.alter_column("events", "project_seq", existing_type=sa.BigInteger(), nullable=True)
    op.drop_column("events", "project_seq")
    op.drop_table("project_event_seq")
