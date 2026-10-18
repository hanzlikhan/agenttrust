"""Public agentic chat endpoint (Live Agent demo page).

POST /api/v1/agent/chat accepts a customer message with no API key (it is
IP rate-limited instead) and runs the Groq LLM loop server-side. Every tool
call the LLM makes flows through the real authorize -> execute path, so the
public demo exercises the same policy engine, approvals, and single-use
grants as the SDK.

Requires GROQ_API_KEY to be set; returns 503 otherwise. Requires the demo
seed (project "demo") to exist; returns 503 otherwise.
"""

import json
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import AppError
from ..gateway.service import execute_tool_call
from ..models import Agent, AgentRun, ApiKey, Approval, Project
from ..policy.service import authorize_tool_call
from ..ratelimit import check_rate_limit
from ..schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentCompleteRequest,
    AgentCompleteResponse,
)
from ..util import utcnow

router = APIRouter(tags=["agent"])

_SYSTEM_PROMPT = """You are a customer support agent for an online store.
When the customer asks for a refund, call the refund_payment tool with the
order id and the amount in minor units (cents: $35 = 3500, $150 = 15000).
Only call the tool when the customer actually requests a refund. Otherwise
just reply conversationally. Keep replies short."""

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "refund_payment",
            "description": "Issue a refund to the customer for an order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order reference, e.g. ORD-100",
                    },
                    "amount_minor": {
                        "type": "integer",
                        "description": "Refund amount in minor units (cents).",
                    },
                    "currency": {
                        "type": "string",
                        "description": "ISO currency code",
                        "default": "USD",
                    },
                },
                "required": ["order_id", "amount_minor"],
            },
        },
    }
]


def _demo_project(db: Session) -> Project:
    project = db.query(Project).filter(Project.name == "demo").first()
    if project is None:
        raise AppError(
            "agent_not_seeded",
            "Demo data not seeded; the public agent needs the 'demo' project.",
            503,
        )
    return project


def _service_key(db: Session, project: Project) -> ApiKey:
    key = (
        db.query(ApiKey)
        .filter(ApiKey.project_id == project.id, ApiKey.name == "demo-seed")
        .first()
    )
    if key is None:
        key = db.query(ApiKey).filter(ApiKey.project_id == project.id).first()
    if key is None:
        raise AppError("agent_not_seeded", "No API key on the demo project.", 503)
    return key


def _open_run(db: Session, project: Project) -> uuid.UUID:
    agent = (
        db.query(Agent)
        .filter(
            Agent.project_id == project.id,
            Agent.name == "web-agent",
            Agent.version == "1.0",
        )
        .first()
    )
    if agent is None:
        agent = Agent(
            project_id=project.id,
            name="web-agent",
            version="1.0",
            environment="prod",
            created_at=utcnow(),
        )
        db.add(agent)
        db.flush()
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        state="RUNNING",
        started_at=utcnow(),
    )
    db.add(run)
    db.commit()
    return run.id


def _call_groq(message: str) -> tuple[str | None, dict[str, Any] | None]:
    """Returns (plain_reply, tool_call_args) — exactly one is not None."""
    try:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            json={
                "model": settings.AGENTTRUST_AGENT_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "tools": _TOOLS,
                "tool_choice": "auto",
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise AppError("llm_unavailable", f"LLM request failed: {exc}", 503) from exc
    if resp.status_code != 200:
        raise AppError(
            "llm_unavailable",
            f"LLM returned HTTP {resp.status_code}.",
            503,
        )
    msg = resp.json()["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    if not calls:
        return msg.get("content") or "(no reply)", None
    args = json.loads(calls[0]["function"]["arguments"])
    if isinstance(args.get("order_id"), str):
        args["order_id"] = args["order_id"].upper()
    return None, args


def _check_ip_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(
        f"agent:{ip}", per_minute=settings.AGENTTRUST_AGENT_RATE_LIMIT_PER_MINUTE
    ):
        raise AppError(
            "rate_limited", "Too many agent requests; try again in a minute.", 429
        )


@router.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(
    payload: AgentChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AgentChatResponse:
    """One turn of the public demo agent: LLM decides, AgentTrust governs."""
    _check_ip_rate_limit(request)
    if not settings.GROQ_API_KEY:
        raise AppError("llm_unavailable", "GROQ_API_KEY is not configured.", 503)

    project = _demo_project(db)
    key = _service_key(db, project)
    run_id = _open_run(db, project)

    reply, tool_args = _call_groq(payload.message)
    if tool_args is None:
        return AgentChatResponse(reply=reply or "", status="no_action")

    dollars = tool_args["amount_minor"] / 100
    tool_label = f"refund_payment(order_id={tool_args['order_id']}, ${dollars:.2f})"

    authz = authorize_tool_call(
        db=db,
        project_id=project.id,
        run_id=run_id,
        tool_name="refund_payment",
        arguments={
            "order_id": tool_args["order_id"],
            "amount_minor": tool_args["amount_minor"],
            "currency": tool_args.get("currency", "USD"),
        },
        idempotency_key=uuid.uuid4().hex,
        requester_key_id=key.id,
    )

    if authz.outcome == "DENY":
        return AgentChatResponse(
            reply=(
                f"The AI wanted to call {tool_label}, but AgentTrust denied it "
                f"({authz.reason_code}). Nothing was executed."
            ),
            status="denied",
            tool_call_id=str(authz.tool_call_id),
        )

    if authz.outcome == "REVIEW":
        return AgentChatResponse(
            reply=(
                f"The AI wants to call {tool_label}. AgentTrust says this needs "
                f"a human — waiting for the shop owner's approval."
            ),
            status="awaiting_approval",
            tool_call_id=str(authz.tool_call_id),
            approval_id=str(authz.approval_id) if authz.approval_id else None,
        )

    # ALLOW — execute immediately through the trusted gateway.
    result = execute_tool_call(
        db=db,
        project_id=project.id,
        call_id=authz.tool_call_id,
        arguments={
            "order_id": tool_args["order_id"],
            "amount_minor": tool_args["amount_minor"],
            "currency": tool_args.get("currency", "USD"),
        },
    )
    remaining = (result.result or {}).get("remaining_minor")
    return AgentChatResponse(
        reply=(
            f"Done — refunded ${dollars:.2f} for order {tool_args['order_id']} "
            f"(auto-approved by policy)."
            + (
                f" Remaining balance: ${remaining / 100:.2f}."
                if remaining is not None
                else ""
            )
        ),
        status="done",
        tool_call_id=str(authz.tool_call_id),
    )


@router.post("/agent/complete", response_model=AgentCompleteResponse)
def agent_complete(
    payload: AgentCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> AgentCompleteResponse:
    """Resolve a pending approval for the public demo agent.

    The frontend polls this after /agent/chat returns `awaiting_approval`.
    When the owner approves on the Approvals page, this executes the grant
    exactly once through the trusted gateway.
    """
    _check_ip_rate_limit(request)
    try:
        approval_uuid = uuid.UUID(payload.approval_id)
    except ValueError as exc:
        raise AppError("invalid_approval", "Malformed approval id.", 422) from exc

    approval = db.get(Approval, approval_uuid)
    if approval is None:
        raise AppError("not_found", "Approval not found.", 404)

    if approval.state == "PENDING":
        return AgentCompleteResponse(status="pending", reply="Still waiting for approval.")
    if approval.state == "REJECTED":
        return AgentCompleteResponse(
            status="rejected", reply="The shop owner rejected this refund."
        )
    if approval.state == "EXPIRED":
        return AgentCompleteResponse(
            status="expired", reply="The approval expired before it was decided."
        )

    # APPROVED — execute against the stored grant (arguments=None), exactly
    # like the SDK's wait_for_approval does.
    result = execute_tool_call(
        db=db,
        project_id=approval.tool_call.project_id,
        call_id=approval.tool_call_id,
        arguments=None,
    )
    refunded = (result.result or {}).get("amount_minor", 0) / 100
    order = (result.result or {}).get("order_id", "")
    return AgentCompleteResponse(
        status="executed",
        reply=f"Approved! Refunded ${refunded:.2f} for order {order}.",
    )
