"""SQLAlchemy ORM models: identity (M01), policy engine (M04/M05/M06),
trusted gateway (M07), and the event/outbox store (M08).

API key secrets are NEVER stored in plaintext: only a lookup prefix and a
SHA-256 hash are persisted (see `security.py`).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .util import utcnow


class Base(DeclarativeBase):
    """Declarative base for all AgentTrust tables."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_projects_owner_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    owner: Mapped["User"] = relationship(back_populates="projects")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="project")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="project")
    agents: Mapped[list["Agent"]] = relationship(back_populates="project")
    runs: Mapped[list["AgentRun"]] = relationship(back_populates="project")
    tool_definitions: Mapped[list["ToolDefinition"]] = relationship(back_populates="project")
    policies: Mapped[list["Policy"]] = relationship(back_populates="project")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_memberships_user_project"),
        Index("ix_memberships_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    project: Mapped["Project"] = relationship(back_populates="memberships")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_key_prefix", "key_prefix"),
        Index("ix_api_keys_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="api_keys")


class Agent(Base):
    """A registered tool-using AI agent (M03). Phase 2: identity only."""

    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_project_name", "project_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="agents")
    runs: Mapped[list["AgentRun"]] = relationship(back_populates="agent")


class AgentRun(Base):
    """One execution session of an agent (M03). Phase 2 states: RUNNING on creation."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_project_time", "project_id", "started_at"),
        Index("ix_agent_runs_trace_id", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="runs")
    agent: Mapped["Agent | None"] = relationship(back_populates="runs")
    tool_calls: Mapped[list["ToolCall"]] = relationship(back_populates="run")


class ToolDefinition(Base):
    """A declared, versioned tool with a typed argument contract (M04)."""

    __tablename__ = "tool_definitions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "slug", "version", name="uq_tool_definitions_project_slug_version"
        ),
        Index("ix_tool_definitions_project_slug", "project_id", "slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risk_class: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="tool_definitions")


class ToolCall(Base):
    """One attempted tool invocation (M06). tool_id is NULL when the tool was
    never registered — the DENY decision is still persisted and audited."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_tool_calls_project_idempotency"
        ),
        Index("ix_tool_calls_run_id", "run_id"),
        Index("ix_tool_calls_project_id", "project_id"),
        # Declared here to match migration 0006 (Phase 8 audit LOW-1).
        Index("ix_tool_calls_requester_key", "requester_key_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tool_definitions.id", ondelete="SET NULL"), nullable=True
    )
    requester_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    args_redacted: Mapped[dict] = mapped_column(JSONB, nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    project: Mapped["Project"] = relationship()
    run: Mapped["AgentRun"] = relationship(back_populates="tool_calls")
    tool: Mapped["ToolDefinition | None"] = relationship()
    decision: Mapped["PolicyDecision | None"] = relationship(back_populates="tool_call")
    approval: Mapped["Approval | None"] = relationship(back_populates="tool_call")


class Policy(Base):
    """A named policy with an immutable, versioned rule set (M05)."""

    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_policies_project_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="policies")
    versions: Mapped[list["PolicyVersion"]] = relationship(
        back_populates="policy",
        primaryjoin="Policy.id == PolicyVersion.policy_id",
        foreign_keys="PolicyVersion.policy_id",
        order_by="PolicyVersion.version",
    )
    active_version: Mapped["PolicyVersion | None"] = relationship(
        foreign_keys=[active_version_id], post_update=True
    )


class PolicyVersion(Base):
    """One immutable version of a policy's rules. Activated versions are never
    mutated: edits create a new version row."""

    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "version", name="uq_policy_versions_policy_version"
        ),
        Index("ix_policy_versions_policy_id", "policy_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    policy: Mapped["Policy"] = relationship(
        back_populates="versions",
        primaryjoin="PolicyVersion.policy_id == Policy.id",
        foreign_keys="PolicyVersion.policy_id",
    )


class PolicyDecision(Base):
    """The recorded outcome of policy evaluation for one tool call (M06).

    version_id is NULL only when no policy version existed to decide under
    (e.g. unregistered tool, or no active policy) — the DENY is still recorded.
    """

    __tablename__ = "policy_decisions"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_policy_decisions_tool_call"),
        Index("ix_policy_decisions_version_id", "version_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[str] = mapped_column(String(512), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    tool_call: Mapped["ToolCall"] = relationship(back_populates="decision")
    version: Mapped["PolicyVersion | None"] = relationship()


class MockOrder(Base):
    """Synthetic payment record: the trusted source of truth for refund policy.

    Money is integer minor units. Balances are mutated only by the Phase 3
    trusted gateway, never by the policy engine.
    """

    __tablename__ = "mock_orders"
    __table_args__ = (UniqueConstraint("order_ref", name="uq_mock_orders_order_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    refundable_remaining_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class ExecutionGrant(Base):
    """Single-use authorization grant minted on ALLOW (M07).

    Bound to one tool call, one canonical argument hash, and one policy
    version. The gateway consumes it inside the execution transaction; a
    consumed or expired grant can never authorize execution.
    """

    __tablename__ = "execution_grants"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_execution_grants_tool_call"),
        Index("ix_execution_grants_tool_call_id", "tool_call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    tool_call: Mapped["ToolCall"] = relationship()


class ToolExecution(Base):
    """The recorded outcome of one protected tool invocation (M07).

    At most one row per tool call: a second execute request for the same call
    returns this row instead of performing a new side effect.
    """

    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("call_id", name="uq_tool_executions_call"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    result_json_redacted: Mapped[dict] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tool_call: Mapped["ToolCall"] = relationship()


class Event(Base):
    """Durable, append-only event record (M08).

    `seq` is a database-wide bigserial (kept for diagnostics). `project_seq`
    is the per-project monotonic sequence assigned atomically by
    `record_event` via `project_event_seq` — it is the SSE `Last-Event-ID`
    cursor contract. Consumers must still deduplicate by `event_id` because
    delivery is at-least-once.
    """

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_project_seq", "project_id", "seq"),
        Index("ix_events_project_project_seq", "project_id", "project_seq"),
        Index("ix_events_run_id", "run_id"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), nullable=False)
    project_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_redacted: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Outbox(Base):
    """Transactional outbox: one row per event awaiting publication (M08).

    The Phase 4 publisher worker claims rows via `next_attempt_at` and marks
    them published. Until then, rows simply accumulate — no delivery is
    attempted in Phase 3.
    """

    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_outbox_event_id"),
        Index("ix_outbox_next_attempt", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    """A durable human-review request for one tool call (M10).

    State machine: PENDING -> APPROVED | REJECTED | EXPIRED. Terminal states
    never transition backwards. `row_version` implements optimistic
    concurrency: a decision writes only when the row still holds the version
    the decider read, so two racing reviewers cannot both decide.
    `requester_key_id` records the credential that triggered the review and
    enforces separation of duties (the requesting credential may never
    decide its own approval).
    """

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("tool_call_id", name="uq_approvals_tool_call"),
        Index("ix_approvals_state_expires", "state", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    requester_key_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    tool_call: Mapped["ToolCall"] = relationship(back_populates="approval")


class ProjectEventSeq(Base):
    """Per-project monotonic event sequence counter (M08, Phase 4).

    `record_event` takes a row lock on the project's counter inside the
    caller's transaction, assigns `events.project_seq = next_seq`, then
    increments. This makes the SSE `Last-Event-ID` cursor a per-project
    monotonic sequence with no gaps introduced by other projects' events.
    """

    __tablename__ = "project_event_seq"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    next_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class Incident(Base):
    """A deterministic detector finding (M11).

    State machine: OPEN -> INVESTIGATING -> RESOLVED | DISMISSED (reopening a
    resolved incident is an audited transition back to INVESTIGATING).
    Terminal states never move backwards otherwise. `tool_call_id` records
    the triggering call for discrete triggers (NULL for scan/pattern
    triggers) and drives dedup: no second OPEN incident for the same
    (category, tool_call_id). `analysis_json` holds the evidence-linked
    investigation report; `analyzer_kind` is ``ollama:<model>`` or
    ``template``.
    """

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_project_status", "project_id", "status"),
        Index("ix_incidents_project_category", "project_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    analysis_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    analyzer_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evidence: Mapped[list["IncidentEvidence"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class IncidentEvidence(Base):
    """One event cited as evidence for an incident (M11).

    The report validator requires every cited evidence_ref to exist in the
    incident's evidence set — a report cannot reference events it was not
    given.
    """

    __tablename__ = "incident_evidence"
    __table_args__ = (
        UniqueConstraint(
            "incident_id", "event_id", name="uq_incident_evidence_pair"
        ),
        Index("ix_incident_evidence_incident", "incident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False
    )

    incident: Mapped["Incident"] = relationship(back_populates="evidence")


class EvaluationCase(Base):
    """One labeled benchmark case (M12).

    ``case_key`` is stable across runs (e.g. ``allow-001``); the runner
    upserts cases idempotently. ``input_json`` holds the tool call arguments
    (plus runner directives under ``_eval``); ``expected_outcome_json`` holds
    ``{outcome, executed, side_effects}``.
    """

    __tablename__ = "evaluation_cases"
    __table_args__ = (Index("ix_evaluation_cases_suite", "suite_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id: Mapped[str] = mapped_column(String(64), nullable=False)
    case_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expected_outcome_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class EvaluationRun(Base):
    """One benchmark execution (M12).

    Versions pin exactly what was measured: dataset version + content hash
    (stored in the report), policy version, and code version (git commit).
    """

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_suite_time", "suite_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        # Tenant owner of this benchmark run. Nullable so pre-existing rows
        # (written before tenant isolation) remain valid; they are invisible
        # to the project-scoped API. The application always sets it for new
        # runs (Phase 8 audit HIGH-1).
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    suite_id: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RUNNING")

    results: Mapped[list["EvaluationResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvaluationResult(Base):
    """Per-case measured outcome vs expectation (M12).

    ``actual_outcome_json`` holds ``{outcome, executed, side_effects}`` as
    measured against the real authorize/execute stack — never asserted.
    """

    __tablename__ = "evaluation_results"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", name="uq_evaluation_results_run_case"),
        Index("ix_evaluation_results_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_cases.id", ondelete="CASCADE"), nullable=False
    )
    actual_outcome_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped["EvaluationRun"] = relationship(back_populates="results")
