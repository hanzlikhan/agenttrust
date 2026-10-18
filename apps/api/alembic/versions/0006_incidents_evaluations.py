"""Phase 7 schema: incident records + evaluation laboratory (M11/M12).

New tables:
- ``incidents``: deterministic detector findings with an explicit state
  machine (OPEN -> INVESTIGATING -> RESOLVED | DISMISSED), severity,
  category, optional evidence-linked analysis report, and analyzer kind.
- ``incident_evidence``: links incidents to the exact events that fired
  them (unique pair; the report validator requires cited IDs to exist here).
- ``evaluation_cases``: the versioned 100-case benchmark dataset
  (unique ``case_key``; upserted by the evaluation runner).
- ``evaluation_runs``: one benchmark execution with dataset/policy/code
  versions and timing.
- ``evaluation_results``: per-case actual outcome vs expectation
  (unique per run+case).

Also adds ``tool_calls.requester_key_id`` (nullable): the credential that
submitted the call, enabling the scan trigger ">=5 DENYs from one key in
10 minutes". Existing rows keep NULL.

Downgrade drops the new tables and the added column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_calls.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("analysis_json", postgresql.JSONB(), nullable=True),
        sa.Column("analyzer_kind", sa.String(64), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incidents_project_status", "incidents", ["project_id", "status"])
    op.create_index(
        "ix_incidents_project_category", "incidents", ["project_id", "category"]
    )

    op.create_table(
        "incident_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(64),
            sa.ForeignKey("events.event_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("incident_id", "event_id", name="uq_incident_evidence_pair"),
    )
    op.create_index(
        "ix_incident_evidence_incident", "incident_evidence", ["incident_id"]
    )

    op.create_table(
        "evaluation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("suite_id", sa.String(64), nullable=False),
        sa.Column("case_key", sa.String(128), nullable=False, unique=True),
        sa.Column("case_type", sa.String(32), nullable=False),
        sa.Column("input_json", postgresql.JSONB(), nullable=False),
        sa.Column("expected_outcome_json", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_evaluation_cases_suite", "evaluation_cases", ["suite_id"])

    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("suite_id", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=True),
        sa.Column("code_version", sa.String(64), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="RUNNING"),
    )
    op.create_index(
        "ix_evaluation_runs_suite_time", "evaluation_runs", ["suite_id", "started_at"]
    )

    op.create_table(
        "evaluation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("evaluation_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actual_outcome_json", postgresql.JSONB(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "run_id", "case_id", name="uq_evaluation_results_run_case"
        ),
    )
    op.create_index("ix_evaluation_results_run", "evaluation_results", ["run_id"])

    op.add_column(
        "tool_calls",
        sa.Column(
            "requester_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tool_calls_requester_key", "tool_calls", ["requester_key_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_calls_requester_key", table_name="tool_calls")
    op.drop_column("tool_calls", "requester_key_id")
    op.drop_index("ix_evaluation_results_run", table_name="evaluation_results")
    op.drop_table("evaluation_results")
    op.drop_index("ix_evaluation_runs_suite_time", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_index("ix_evaluation_cases_suite", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_index("ix_incident_evidence_incident", table_name="incident_evidence")
    op.drop_table("incident_evidence")
    op.drop_index("ix_incidents_project_category", table_name="incidents")
    op.drop_index("ix_incidents_project_status", table_name="incidents")
    op.drop_table("incidents")
