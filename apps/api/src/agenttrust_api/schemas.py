"""Pydantic request/response schemas for the Phase 1 API surface."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str
    retryable: bool = False


class HealthLiveResponse(BaseModel):
    status: str = "ok"
    service: str = "agenttrust-api"
    version: str = "0.1.0"
    timestamp: datetime


class HealthReadyResponse(BaseModel):
    status: str = "ready"
    database: str = "up"
    timestamp: datetime


class KeyCreateRequest(BaseModel):
    project_id: UUID
    name: str = Field(default="", max_length=128)
    # Least privilege by default (Phase 8 audit MEDIUM-5): an omitted
    # scopes list mints a key with NO permissions. Callers must request
    # the scopes they need explicitly (e.g. ["*"] for full access).
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class KeyCreateResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    key_prefix: str
    api_key: str  # the raw secret — returned ONLY on creation, never stored
    scopes: list[str]
    expires_at: datetime | None
    created_at: datetime


class ApiKeyPublic(BaseModel):
    """Redacted key record: prefix only. Never includes the hash or raw secret."""

    id: UUID
    project_id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyListResponse(BaseModel):
    keys: list[ApiKeyPublic]


class KeyRevokeResponse(BaseModel):
    id: UUID
    revoked_at: datetime


class WhoAmIResponse(BaseModel):
    project_id: UUID
    project_name: str
    key_prefix: str
    scopes: list[str]


# ---------------------------------------------------------------------------
# Phase 2: runs, tool registry, policies, authorization (M03/M04/M05/M06)
# ---------------------------------------------------------------------------


class RunCreateRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=128)
    agent_version: str = Field(default="0.1.0", max_length=32)
    environment: str = Field(default="local", max_length=32)


class RunCreateResponse(BaseModel):
    run_id: UUID
    trace_id: UUID
    agent_name: str
    agent_version: str
    state: str
    started_at: datetime


RiskClass = Literal["read_only", "write", "high_impact"]


class ToolRegisterRequest(BaseModel):
    project_id: UUID
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(ge=1)
    schema_json: dict[str, Any]
    risk_class: RiskClass


class ToolDefinitionResponse(BaseModel):
    id: UUID
    project_id: UUID
    slug: str
    version: int
    schema_json: dict[str, Any]
    risk_class: str
    created_at: datetime


class ToolListResponse(BaseModel):
    tools: list[ToolDefinitionResponse]


class PolicyCreateRequest(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=128)
    rules_json: dict[str, Any]  # validated against RefundPolicyConfig on receipt


class PolicyVersionResponse(BaseModel):
    id: UUID
    version: int
    rules_json: dict[str, Any]
    created_by: str
    activated_at: datetime | None
    created_at: datetime


class PolicyResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    active_version_id: UUID | None
    versions: list[PolicyVersionResponse]
    created_at: datetime


class PolicyListResponse(BaseModel):
    policies: list[PolicyResponse]


class PolicyActivateResponse(BaseModel):
    id: UUID
    name: str
    active_version_id: UUID
    activated_version: int
    activated_at: datetime


class SimulateRequest(BaseModel):
    project_id: UUID
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]


class SimulateResponse(BaseModel):
    outcome: Literal["ALLOW", "DENY", "REVIEW"]
    reason_code: str
    policy_version: int | None
    evaluated_with_draft: bool
    explanation: str


class AuthorizeRequest(BaseModel):
    run_id: UUID
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    idempotency_key: str = Field(min_length=1, max_length=128)


class AuthorizeResponse(BaseModel):
    tool_call_id: UUID
    decision_id: UUID
    outcome: Literal["ALLOW", "DENY", "REVIEW"]
    reason_code: str
    policy_version: int | None
    decided_at: datetime
    explanation: str
    approval_id: UUID | None = Field(
        default=None,
        description=(
            "Set when outcome is REVIEW: the pending approval created for this "
            "tool call. Null for ALLOW/DENY."
        ),
    )


# ---------------------------------------------------------------------------
# Phase 3: trusted gateway execution (M07)
# ---------------------------------------------------------------------------


class ExecuteRequest(BaseModel):
    arguments: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional echo of the authorized arguments. When present, the gateway "
            "re-hashes them and rejects the request (409) if they differ from the "
            "authorized canonical hash. Omit to execute against the stored grant."
        ),
    )


class ExecuteResponse(BaseModel):
    tool_call_id: UUID
    execution_id: UUID
    state: str
    result: dict[str, Any]
    replayed: bool = Field(
        description="True when a previous execution's stored result was returned "
        "instead of performing a new side effect."
    )


# ---------------------------------------------------------------------------
# Phase 4: event ingestion + dashboard reads (M08/M09)
# ---------------------------------------------------------------------------


class EventIngestItem(BaseModel):
    kind: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_.]{0,63}$",
        description="Namespaced event kind, e.g. 'agent.thinking'.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Already-redacted telemetry payload. Treated as untrusted.",
    )


class EventIngestRequest(BaseModel):
    events: list[EventIngestItem] = Field(min_length=1, max_length=100)


class EventIngestResponse(BaseModel):
    run_id: UUID
    accepted: int
    first_seq: int | None
    last_seq: int | None
    received_at: datetime


class DashboardSummary(BaseModel):
    project_id: UUID
    runs_total: int
    runs_by_state: dict[str, int]
    tool_calls_total: int
    decisions_total: int
    decisions_by_outcome: dict[str, int]
    executions_total: int
    events_total: int
    outbox_pending: int


class MetricsResponse(BaseModel):
    """Built-in operational metrics (M17) — counts from committed rows only."""

    project_id: UUID
    decisions_by_outcome: dict[str, int]
    executions_total: int
    active_approvals: int
    incidents_by_status: dict[str, int]
    generated_at: datetime


class RunSummaryItem(BaseModel):
    run_id: UUID
    trace_id: UUID
    agent_name: str
    agent_version: str
    state: str
    started_at: datetime
    ended_at: datetime | None
    tool_call_count: int


class RunListResponse(BaseModel):
    runs: list[RunSummaryItem]
    total: int
    limit: int
    offset: int


class EventPublic(BaseModel):
    event_id: str
    kind: str
    project_seq: int
    run_id: UUID | None
    received_at: datetime
    payload: dict[str, Any]


class RunDetailResponse(BaseModel):
    run_id: UUID
    trace_id: UUID
    project_id: UUID
    agent_name: str
    agent_version: str
    state: str
    started_at: datetime
    ended_at: datetime | None
    tool_call_count: int
    events: list[EventPublic]


# ---------------------------------------------------------------------------
# Phase 5: human approvals (M10)
# ---------------------------------------------------------------------------

ApprovalState = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED"]


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"] = Field(
        description="The reviewer's verdict."
    )
    reason: str | None = Field(
        default=None,
        max_length=256,
        description="Optional reviewer note, stored with the decision.",
    )
    expected_row_version: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Optimistic-concurrency guard: the row_version the reviewer saw. "
            "When omitted, the server reads the current version and still "
            "protects the read-then-write window; a stale explicit version "
            "yields 409."
        ),
    )


class ApprovalDecisionResponse(BaseModel):
    approval_id: UUID
    state: ApprovalState
    decided_at: datetime | None
    row_version: int
    reason: str | None
    grant_id: UUID | None = Field(
        default=None,
        description="Set when the decision is APPROVED: the single-use "
        "execution grant minted for the approved call.",
    )
    grant_expires_at: datetime | None = None


class ApprovalQueueItem(BaseModel):
    approval_id: UUID
    tool_call_id: UUID
    tool_name: str
    state: ApprovalState
    reason_code: str
    order_id: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    expires_at: datetime
    row_version: int
    created_at: datetime


class ApprovalQueueResponse(BaseModel):
    approvals: list[ApprovalQueueItem]
    total: int
    limit: int
    offset: int


class ApprovalToolCallInfo(BaseModel):
    tool_call_id: UUID
    tool_name: str
    args_redacted: dict[str, Any]
    args_hash: str
    idempotency_key: str
    state: str


class ApprovalDecisionInfo(BaseModel):
    decision_id: UUID
    outcome: str
    reason_code: str
    explanation: str
    policy_version: int | None


class ApprovalOrderFacts(BaseModel):
    order_ref: str
    eligible: bool
    remaining_minor: int
    currency: str


class ApprovalRequesterInfo(BaseModel):
    key_name: str
    key_prefix: str


class ApprovalDetailResponse(BaseModel):
    approval_id: UUID
    tool_call_id: UUID
    state: ApprovalState
    reason: str | None
    expires_at: datetime
    decided_at: datetime | None
    row_version: int
    created_at: datetime
    tool_call: ApprovalToolCallInfo
    decision: ApprovalDecisionInfo
    order_facts: ApprovalOrderFacts | None
    requester: ApprovalRequesterInfo
    reviewer_key_prefix: str | None
    events: list[EventPublic]


class ApprovalStatusResponse(BaseModel):
    approval_id: UUID
    tool_call_id: UUID
    state: ApprovalState
    expires_at: datetime
    decided_at: datetime | None


# ---------------------------------------------------------------------------
# Phase 6: agents directory + analytics (M09 read surface)
# ---------------------------------------------------------------------------


class AgentSummaryItem(BaseModel):
    agent_id: UUID
    name: str
    version: str
    environment: str
    run_count: int
    last_run_at: datetime | None


class AgentListResponse(BaseModel):
    agents: list[AgentSummaryItem]
    total: int
    limit: int
    offset: int


class AgentRunItem(BaseModel):
    run_id: UUID
    trace_id: UUID
    state: str
    started_at: datetime
    ended_at: datetime | None
    tool_call_count: int


class AgentDetailResponse(BaseModel):
    agent_id: UUID
    name: str
    version: str
    environment: str
    created_at: datetime
    recent_runs: list[AgentRunItem]
    total_runs: int


class AnalyticsDayItem(BaseModel):
    """Decisions on one UTC calendar day. Outcomes with no decisions are 0."""

    day: str
    ALLOW: int
    DENY: int
    REVIEW: int


class PercentileStats(BaseModel):
    """Nearest-rank percentiles; p50/p95 are null when count is 0."""

    p50: float | None
    p95: float | None
    count: int


class DeniedToolItem(BaseModel):
    tool_name: str
    deny_count: int


class AnalyticsResponse(BaseModel):
    window_days: int
    decisions_by_day: list[AnalyticsDayItem]
    execution_latency_ms: PercentileStats
    top_denied_tools: list[DeniedToolItem]
    approval_turnaround_s: PercentileStats


# ---------------------------------------------------------------------------
# Incidents (M11, Phase 7)
# ---------------------------------------------------------------------------


class IncidentListItem(BaseModel):
    incident_id: UUID
    category: str
    severity: str
    status: str
    opened_at: datetime
    resolved_at: datetime | None
    summary: str
    evidence_count: int


class IncidentListResponse(BaseModel):
    incidents: list[IncidentListItem]
    total: int
    limit: int
    offset: int


class IncidentCausePublic(BaseModel):
    cause: str
    confidence: str
    evidence_refs: list[str]


class IncidentAnalysisPublic(BaseModel):
    analyzer_kind: str
    classification: str
    summary: str
    possible_causes: list[IncidentCausePublic]
    evidence_refs: list[str]
    uncertainty: str
    recommended_checks: list[str]
    analyzed_at: datetime


class IncidentDetailResponse(BaseModel):
    incident_id: UUID
    project_id: UUID
    category: str
    severity: str
    status: str
    opened_at: datetime
    resolved_at: datetime | None
    summary: str
    tool_call_id: UUID | None
    analysis: IncidentAnalysisPublic | None
    evidence: list[EventPublic]


class IncidentAnalyzeResponse(BaseModel):
    incident_id: UUID
    report: IncidentAnalysisPublic


class IncidentScanResponse(BaseModel):
    incidents_created: int
    checked: dict[str, int]


class IncidentStatusRequest(BaseModel):
    status: str = Field(pattern=r"^(investigating|resolved|dismissed)$")


class IncidentStatusResponse(BaseModel):
    incident_id: UUID
    status: str
    resolved_at: datetime | None


# ---------------------------------------------------------------------------
# Evaluations (M12, Phase 7)
# ---------------------------------------------------------------------------


class EvaluationRunSummary(BaseModel):
    run_id: UUID
    suite_id: str
    dataset_version: str
    policy_version: str | None
    code_version: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    total: int
    passed: int
    failed: int


class EvaluationRunListResponse(BaseModel):
    runs: list[EvaluationRunSummary]
    total: int
    limit: int
    offset: int


class LatencyStats(BaseModel):
    p50: float | None
    p95: float | None
    max: float | None


class EvaluationMetrics(BaseModel):
    total: int
    passed: int
    failed: int
    accuracy: float | None
    false_allow: int
    false_deny: int
    unauthorized_executions: int
    duplicate_effects: int
    latency_ms: LatencyStats
    by_type: dict[str, dict[str, int]]


class CaseExpectation(BaseModel):
    outcome: str
    executed: bool


class EvaluationCaseResult(BaseModel):
    case_key: str
    case_type: str
    expected: CaseExpectation
    actual: CaseExpectation
    passed: bool
    latency_ms: int
    error: str | None


class EvaluationRunDetailResponse(BaseModel):
    run: EvaluationRunSummary
    metrics: EvaluationMetrics
    results: list[EvaluationCaseResult]


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_id: str = Field(min_length=1, max_length=64)


class AgentChatResponse(BaseModel):
    reply: str
    status: str  # done | denied | awaiting_approval | no_action
    tool_call_id: str | None = None
    approval_id: str | None = None


class AgentCompleteRequest(BaseModel):
    approval_id: str = Field(min_length=1, max_length=64)


class AgentCompleteResponse(BaseModel):
    status: str  # executed | pending | rejected | expired
    reply: str
