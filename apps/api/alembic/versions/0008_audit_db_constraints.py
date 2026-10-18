"""Phase 8 audit DB fixes: dedup enforcement + drift alignment.

- MEDIUM-6: UNIQUE (project_id, project_seq) on events — the per-project
  monotonicity invariant was application-only.
- MEDIUM-1: partial unique indexes enforcing incident dedup at the DB
  level (check-then-act races could create duplicates).
- LOW-1: align three migration/model drifts (approvals constraint name,
  incidents.summary type, missing tool_calls index declaration is a model
  change, not a migration change).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # MEDIUM-6: DB-level uniqueness for the SSE resume contract.
    op.create_unique_constraint(
        "uq_events_project_seq", "events", ["project_id", "project_seq"]
    )

    # MEDIUM-1: incident dedup enforced by the database.
    # Discrete incidents: one OPEN per (project, category, tool_call).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_incidents_open_discrete
        ON incidents (project_id, category, tool_call_id)
        WHERE status = 'OPEN' AND tool_call_id IS NOT NULL
        """
    )
    # Scan-family incidents: one OPEN per (project, category) when there is
    # no tool call attached.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_incidents_open_scan
        ON incidents (project_id, category)
        WHERE status = 'OPEN' AND tool_call_id IS NULL
        """
    )

    # LOW-1.1: rename the auto-named approvals constraint to the name the
    # model declares.
    op.execute(
        "ALTER TABLE approvals RENAME CONSTRAINT "
        "approvals_tool_call_id_key TO uq_approvals_tool_call"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE approvals RENAME CONSTRAINT "
        "uq_approvals_tool_call TO approvals_tool_call_id_key"
    )
    op.execute("DROP INDEX IF EXISTS uq_incidents_open_scan")
    op.execute("DROP INDEX IF EXISTS uq_incidents_open_discrete")
    op.drop_constraint("uq_events_project_seq", "events", type_="unique")
