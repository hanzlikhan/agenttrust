"""Evidence-based incident investigation (M11).

An explicit LangGraph workflow::

    collect_evidence -> analyze -> validate

The collector loads only redacted, authorized records. The analyzer is
either a locally-hosted Ollama model or a deterministic template —
never an enforcement authority. The validator rejects reports that cite
evidence the incident was not given, that omit uncertainty, or that
claim the analyzer took actions (approved, executed, changed policy).

The graph binds NO tools: the analyzer can only read the evidence it is
handed and return a JSON report. ``test_analyzer_binds_no_tools`` asserts
this structurally.
"""

import json
import re
from typing import Any, TypedDict
from uuid import UUID

import httpx
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ..config import settings
from ..deps import AppError
from ..models import PolicyDecision, ToolCall
from .service import evidence_events, scoped_incident, store_analysis

# ---------------------------------------------------------------------------
# Report schema
# ---------------------------------------------------------------------------


class PossibleCause(BaseModel):
    cause: str = Field(min_length=1, max_length=1000)
    confidence: str = Field(pattern=r"^(low|medium|high)$")
    evidence_refs: list[str] = Field(min_length=1)


class IncidentReport(BaseModel):
    classification: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2000)
    possible_causes: list[PossibleCause] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    uncertainty: str = Field(min_length=1, max_length=2000)
    recommended_checks: list[str] = Field(min_length=1)


# Phrases that would mean the analyzer claims to have acted. Reports are
# analysis only; the model may not approve, execute, or change policy.
FORBIDDEN_CLAIM_PATTERNS = [
    r"policy\s+(was|were|has been|have been)\s+(updated|changed|modified|deactivated)",
    r"\bi\s+(approved|executed|modified|changed)\b",
    r"\bgrant\s+(was\s+)?(minted|issued|created)\s+by\s+(me|the\s+analyzer)\b",
    r"\baction\s+was\s+taken\b",
]


class InvestigationState(TypedDict):
    incident_id: str
    project_id: str
    evidence_refs: list[str]
    policy_snapshot: dict[str, Any]
    analysis: dict[str, Any] | None
    analyzer_kind: str
    validation_errors: list[str]
    status: str


# ---------------------------------------------------------------------------
# Evidence collector (read-only)
# ---------------------------------------------------------------------------


def _collect_evidence(db: Session, incident_id: UUID, project_id: UUID) -> dict[str, Any]:
    incident = scoped_incident(db, incident_id, project_id)
    events = evidence_events(db, incident)
    evidence_refs = [e.event_id for e in events]

    policy_snapshot: dict[str, Any] = {}
    if incident.tool_call_id is not None:
        call = db.get(ToolCall, incident.tool_call_id)
        decision = (
            db.query(PolicyDecision)
            .filter(PolicyDecision.tool_call_id == incident.tool_call_id)
            .one_or_none()
        )
        policy_snapshot = {
            "tool_call_id": str(incident.tool_call_id),
            "tool_call_state": call.state if call else None,
            "args_redacted": call.args_redacted if call else None,
            "decision_outcome": decision.outcome if decision else None,
            "decision_reason": decision.reason_code if decision else None,
            "decision_explanation": decision.explanation if decision else None,
            "policy_version_id": (
                str(decision.version_id)
                if decision and decision.version_id
                else None
            ),
        }

    evidence_payloads = [
        {
            "event_id": e.event_id,
            "kind": e.kind,
            "project_seq": e.project_seq,
            "received_at": e.received_at.isoformat(),
            "payload": e.payload_redacted,
        }
        for e in events
    ]
    return {
        "evidence_refs": evidence_refs,
        "policy_snapshot": policy_snapshot,
        "evidence_payloads": evidence_payloads,
        "category": incident.category,
        "severity": incident.severity,
        "summary": incident.summary,
    }


# ---------------------------------------------------------------------------
# Analyzer: Ollama with deterministic template fallback
# ---------------------------------------------------------------------------

ANALYZER_SYSTEM_PROMPT = """You are an incident-analysis assistant for AgentTrust, a pre-execution \
authorization platform for AI agents. You are given redacted evidence (event \
records) about a security incident. You MUST respond with JSON only, matching \
this schema exactly:
{
  "classification": "short incident classification",
  "summary": "2-3 sentence factual summary grounded ONLY in the evidence",
  "possible_causes": [{"cause": "...", "confidence": "low|medium|high",
                       "evidence_refs": ["<event_id>", ...]}],
  "evidence_refs": ["<event_id>", ...],
  "uncertainty": "what is NOT known from the evidence (must be non-empty)",
  "recommended_checks": ["concrete engineering check", ...]
}
RULES:
- Every evidence_ref you cite MUST be an event_id from the evidence given. Never invent IDs.
- Distinguish facts (in evidence) from hypotheses (label confidence accordingly).
- You are analysis-only: you cannot and did not approve, execute, or change anything. \
Never claim otherwise.
- The "uncertainty" field must be non-empty and honest."""


def _ollama_analyze(
    *, evidence: list[dict[str, Any]], category: str, model: str, timeout_s: int
) -> dict[str, Any]:
    """Ask the local Ollama model for a JSON report. Raises on any failure."""
    prompt = (
        ANALYZER_SYSTEM_PROMPT
        + "\n\nINCIDENT CATEGORY: "
        + category
        + "\nEVIDENCE (redacted):\n"
        + json.dumps(evidence, indent=2, default=str)[:12000]
    )
    response = httpx.post(
        f"{settings.AGENTTRUST_OLLAMA_URL.rstrip('/')}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        timeout=timeout_s,
    )
    response.raise_for_status()
    body = response.json()
    return json.loads(body["response"])


_TEMPLATE_CLASSIFICATIONS = {
    "authorization_tamper": "Authorization tampering attempt",
    "grant_replay": "Duplicate execution-grant presentation",
    "amount_overflow": "Anomalous excessive-amount attempt",
    "repeated_denials": "Repeated policy denials from one credential",
    "tamper_pattern": "Sustained argument-tampering pattern",
}

_TEMPLATE_CAUSES = {
    "authorization_tamper": (
        "The client submitted tool arguments that differ from the canonical "
        "arguments the policy authorized (hash mismatch at the gateway).",
        "high",
    ),
    "grant_replay": (
        "A single-use execution grant was presented after consumption; the "
        "transactional claim prevented a second side effect.",
        "high",
    ),
    "amount_overflow": (
        "The requested amount far exceeds normal policy thresholds, "
        "consistent with a misconfigured client or a prompt-injection "
        "attempt routed through the agent.",
        "medium",
    ),
    "repeated_denials": (
        "One credential is repeatedly attempting actions the policy denies; "
        "consistent with a stuck retry loop or probing behavior.",
        "medium",
    ),
    "tamper_pattern": (
        "Multiple independent argument-tampering rejections indicate a "
        "client that is systematically mutating authorized arguments.",
        "high",
    ),
}

_TEMPLATE_CHECKS = {
    "authorization_tamper": [
        "Audit the client integration for argument mutation between authorize and execute.",
        "Verify the SDK canonicalizes arguments identically on both calls.",
        "Check whether the tampering client credential should be rotated.",
    ],
    "grant_replay": [
        "Confirm the client treats 200-replayed execute responses as success instead of retrying.",
        "Review gateway logs for the grant lifecycle of the affected call.",
    ],
    "amount_overflow": [
        "Review the agent prompt and tool schema for amount handling.",
        "Consider whether the review threshold still matches business risk.",
    ],
    "repeated_denials": [
        "Identify the owning integration for the denied credential.",
        "Check for a retry loop that ignores DENY outcomes.",
    ],
    "tamper_pattern": [
        "Rotate the affected credential and review its recent call history.",
        "Escalate to a human reviewer: sustained tampering is adversarial until proven otherwise.",
    ],
}


def _template_analyze(
    *,
    evidence: list[dict[str, Any]],
    evidence_refs: list[str],
    category: str,
    reason_code: str | None,
) -> dict[str, Any]:
    """Deterministic fallback report built only from recorded evidence."""
    classification = _TEMPLATE_CLASSIFICATIONS.get(category, "Security incident")
    cause_text, confidence = _TEMPLATE_CAUSES.get(
        category, ("Recorded evidence indicates a policy-relevant anomaly.", "low")
    )
    reason = f" Policy reason code: {reason_code}." if reason_code else ""
    return {
        "classification": classification,
        "summary": (
            f"Deterministic analysis of {len(evidence_refs)} evidence event(s) "
            f"for a '{category}' incident.{reason} No model was involved; "
            "every statement below is derived from recorded events."
        ),
        "possible_causes": [
            {
                "cause": cause_text,
                "confidence": confidence,
                "evidence_refs": evidence_refs[:5],
            }
        ],
        "evidence_refs": evidence_refs,
        "uncertainty": (
            "Template analysis cannot determine client intent — it reports "
            "only what the recorded events show. Whether the trigger was "
            "malicious, buggy, or misconfigured is unknown from this evidence."
        ),
        "recommended_checks": _TEMPLATE_CHECKS.get(
            category, ["Review the incident evidence timeline with a human reviewer."]
        ),
    }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_report(
    report: dict[str, Any], *, known_evidence_refs: set[str]
) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []
    try:
        parsed = IncidentReport.model_validate(report)
    except ValidationError as exc:
        return [f"schema: {e['loc']}: {e['msg']}" for e in exc.errors()]

    cited = set(parsed.evidence_refs)
    for cause in parsed.possible_causes:
        cited.update(cause.evidence_refs)
    unknown = cited - known_evidence_refs
    if unknown:
        errors.append(
            "evidence_refs unknown to this incident: " + ", ".join(sorted(unknown))
        )

    text = " ".join(
        [parsed.summary]
        + [c.cause for c in parsed.possible_causes]
        + [" ".join(parsed.recommended_checks)]
    ).lower()
    for pattern in FORBIDDEN_CLAIM_PATTERNS:
        if re.search(pattern, text):
            errors.append(f"forbidden claim pattern matched: {pattern}")
    return errors


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_investigation_graph(db: Session, *, incident_id: UUID, project_id: UUID):
    """Build and compile the collect -> analyze -> validate graph.

    Exposed for tests: the graph binds NO tools — nodes are pure functions
    over the investigation state.
    """
    collected: dict[str, Any] = {}

    def collect_evidence(state: InvestigationState) -> dict[str, Any]:
        nonlocal collected
        collected = _collect_evidence(db, incident_id, project_id)
        return {
            "evidence_refs": collected["evidence_refs"],
            "policy_snapshot": collected["policy_snapshot"],
            "status": "collected",
        }

    def analyze(state: InvestigationState) -> dict[str, Any]:
        model = settings.AGENTTRUST_OLLAMA_MODEL
        evidence = collected["evidence_payloads"]
        reason = collected["policy_snapshot"].get("decision_reason")
        try:
            report = _ollama_analyze(
                evidence=evidence,
                category=collected["category"],
                model=model,
                timeout_s=settings.AGENTTRUST_ANALYZE_TIMEOUT_SECONDS,
            )
            return {
                "analysis": report,
                "analyzer_kind": f"ollama:{model}",
                "status": "analyzed",
            }
        except Exception:
            report = _template_analyze(
                evidence=evidence,
                evidence_refs=state["evidence_refs"],
                category=collected["category"],
                reason_code=reason,
            )
            return {
                "analysis": report,
                "analyzer_kind": "template",
                "status": "analyzed",
            }

    def validate(state: InvestigationState) -> dict[str, Any]:
        errors = validate_report(
            state["analysis"] or {}, known_evidence_refs=set(state["evidence_refs"])
        )
        return {
            "validation_errors": errors,
            "status": "valid" if not errors else "invalid",
        }

    graph = StateGraph(InvestigationState)
    graph.add_node("collect_evidence", collect_evidence)
    graph.add_node("analyze", analyze)
    graph.add_node("validate", validate)
    graph.set_entry_point("collect_evidence")
    graph.add_edge("collect_evidence", "analyze")
    graph.add_edge("analyze", "validate")
    graph.add_edge("validate", END)
    return graph.compile()


def run_investigation(
    db: Session, *, incident_id: UUID, project_id: UUID
) -> tuple[dict[str, Any], str]:
    """Run collect -> analyze -> validate and store the report.

    Returns (report, analyzer_kind). Raises AppError when validation fails.
    The graph binds no tools: nodes are pure functions over the state.
    """
    compiled = build_investigation_graph(db, incident_id=incident_id, project_id=project_id)

    final = compiled.invoke(
        {
            "incident_id": str(incident_id),
            "project_id": str(project_id),
            "evidence_refs": [],
            "policy_snapshot": {},
            "analysis": None,
            "analyzer_kind": "template",
            "validation_errors": [],
            "status": "started",
        }
    )
    if final["status"] != "valid":
        raise AppError(
            "analysis_invalid",
            "Incident analysis failed validation: "
            + "; ".join(final["validation_errors"][:5]),
            502,
        )
    analyzer_kind = final["analyzer_kind"]
    incident = scoped_incident(db, incident_id, project_id)
    store_analysis(
        db, incident=incident, report=final["analysis"], analyzer_kind=analyzer_kind
    )
    return final["analysis"], analyzer_kind
