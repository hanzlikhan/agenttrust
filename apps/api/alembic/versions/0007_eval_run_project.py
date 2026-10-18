"""Phase 8 audit fix: tenant-isolate evaluation runs (HIGH-1).

Adds ``evaluation_runs.project_id`` (nullable; pre-existing rows keep NULL
and are invisible to the project-scoped API) so benchmark results belong to
the project that requested them. The application always sets it for new
runs; list/detail/report endpoints filter by the caller's project.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_evaluation_runs_project_id", "evaluation_runs", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_project_id", table_name="evaluation_runs")
    op.drop_column("evaluation_runs", "project_id")
