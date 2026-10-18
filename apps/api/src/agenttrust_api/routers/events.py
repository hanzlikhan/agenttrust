"""Real-time event streaming (M08) and SDK event ingestion (M02).

``GET /api/v1/events/stream`` is a Server-Sent Events endpoint:

- Auth is a project API key in the ``api_key`` query parameter, because the
  browser EventSource API cannot send Authorization headers. See
  ``require_api_key_query`` and ADR-027 for the limitations.
- The resume cursor is the per-project monotonic ``events.project_seq``.
  The ``Last-Event-ID`` request header wins; the ``cursor`` query parameter
  is accepted as a fallback for clients that manage reconnection manually
  (a fresh browser EventSource does not resend Last-Event-ID).
- Backfill first (everything with ``project_seq > cursor``), then a live
  tail that polls the durable events table. Delivery is at-least-once:
  clients MUST deduplicate by ``event_id``. The SSE ``id:`` field carries
  ``project_seq`` so reconnects resume without gaps. NOTE: events are sent
  as plain ``message`` events (no ``event:`` line) — the browser
  EventSource API has no wildcard subscription for named events, so a
  generic live dashboard could not consume typed events; the kind travels
  in the data payload envelope instead (ADR-029).
- The dashboard is eventually consistent with committed events and is never
  the security authority for executing tools.

``POST /api/v1/runs/{run_id}/events`` ingests SDK-reported telemetry events
into the same durable store, in one transaction.
"""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import SCOPE_AGENT_RUN, AppError, require_api_key_query, require_scopes
from ..events import record_event
from ..models import AgentRun, ApiKey, Event
from ..schemas import (
    EventIngestRequest,
    EventIngestResponse,
)
from ..util import utcnow

router = APIRouter(tags=["events"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

# Upper bound on rows scanned per poll so one slow consumer cannot pin the
# connection on a huge backlog; backfill loops until caught up.
_BACKFILL_BATCH = 1000

# Telemetry ingest hardening (Phase 8 audit MEDIUM-4): the server does not
# trust clients to redact. Payloads are scrubbed for secret-shaped keys and
# capped in size before persistence.
_MAX_TELEMETRY_PAYLOAD_BYTES = 32768
_SECRET_KEY_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|bearer|auth|credential|"
    r"private[_-]?key|access[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"^(sk-|sk_|at_|ghp_|gho_|xox[bap]-|AKIA|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
)


def scrub_telemetry_payload(value: object, _depth: int = 0) -> object:
    """Redact secret-shaped keys/values from untrusted telemetry payloads.

    Depth-capped to avoid pathological nesting; non-JSON scalars pass
    through unchanged.
    """
    if _depth > 8:
        return "[REDACTED: max depth]"
    if isinstance(value, dict):
        scrubbed = {}
        for k, v in value.items():
            if isinstance(k, str) and _SECRET_KEY_PATTERN.search(k):
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_telemetry_payload(v, _depth + 1)
        return scrubbed
    if isinstance(value, list):
        return [scrub_telemetry_payload(v, _depth + 1) for v in value]
    if isinstance(value, str) and _SECRET_VALUE_PATTERN.match(value):
        return "[REDACTED]"
    return value


def _parse_cursor(request: Request, cursor_param: str | None) -> int:
    """Resolve the resume cursor: Last-Event-ID header, then ?cursor=, else 0."""
    raw = request.headers.get("last-event-id")
    if raw is None or raw == "":
        raw = cursor_param
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise AppError(
            "invalid_cursor", "Last-Event-ID / cursor must be an integer.", 400
        ) from exc
    if value < 0:
        raise AppError("invalid_cursor", "Last-Event-ID / cursor must be >= 0.", 400)
    return value


def _envelope(event: Event) -> str:
    """Serialize one event to a single SSE data payload."""
    received = event.received_at
    if isinstance(received, datetime):
        received_iso = received.isoformat()
    else:
        received_iso = str(received)
    payload = {
        "event_id": event.event_id,
        "kind": event.kind,
        "project_id": str(event.project_id),
        "run_id": str(event.run_id) if event.run_id else None,
        "project_seq": event.project_seq,
        "received_at": received_iso,
        "payload": event.payload_redacted,
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _fetch_new(project_id: UUID, after_seq: int, limit: int = _BACKFILL_BATCH) -> list[Event]:
    """Return events for one project with project_seq > after_seq, in order."""
    db = SessionLocal()
    try:
        return (
            db.query(Event)
            .filter(Event.project_id == project_id, Event.project_seq > after_seq)
            .order_by(Event.project_seq.asc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


async def _event_generator(
    project_id: UUID,
    start_cursor: int,
    poll_seconds: float,
    heartbeat_seconds: float,
    max_seconds: float,
) -> AsyncIterator[str]:
    last_sent = start_cursor
    started = time.monotonic()
    idle_since = started
    # 1. Backfill: everything the client has not seen yet, oldest first.
    while True:
        batch = _fetch_new(project_id, last_sent)
        if not batch:
            break
        for event in batch:
            yield f"id: {event.project_seq}\ndata: {_envelope(event)}\n\n"
            last_sent = event.project_seq
        idle_since = time.monotonic()
    # 2. Live tail: poll the durable table; heartbeat when idle.
    while True:
        now = time.monotonic()
        if now - started >= max_seconds:
            break
        batch = _fetch_new(project_id, last_sent)
        if batch:
            for event in batch:
                yield f"id: {event.project_seq}\ndata: {_envelope(event)}\n\n"
                last_sent = event.project_seq
            idle_since = time.monotonic()
        elif now - idle_since >= heartbeat_seconds:
            yield ": ping\n\n"
            idle_since = now
        await asyncio.sleep(poll_seconds)


@router.get("/events/stream")
def stream_events(
    request: Request,
    cursor: str | None = Query(default=None, description="Resume cursor (fallback)"),
    key: ApiKey = Depends(require_api_key_query),
) -> StreamingResponse:
    """Project-scoped SSE stream with backfill and resume support."""
    start_cursor = _parse_cursor(request, cursor)
    generator = _event_generator(
        key.project_id,
        start_cursor,
        poll_seconds=settings.AGENTTRUST_SSE_POLL_SECONDS,
        heartbeat_seconds=settings.AGENTTRUST_SSE_HEARTBEAT_SECONDS,
        max_seconds=settings.AGENTTRUST_SSE_MAX_SECONDS,
    )
    return StreamingResponse(
        generator, media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.post(
    "/runs/{run_id}/events", status_code=201, response_model=EventIngestResponse
)
def ingest_run_events(
    run_id: UUID,
    payload: EventIngestRequest,
    db: Session = Depends(get_db),
    key: ApiKey = Depends(require_scopes(SCOPE_AGENT_RUN, limit_per_minute=False)),
) -> EventIngestResponse:
    """Ingest SDK-reported telemetry events for one run, in one transaction.

    Payloads are treated as untrusted: kinds are restricted to a safe token
    pattern and payloads are size-limited. This endpoint records telemetry
    only — it never authorizes or executes tools.
    """
    run = (
        db.query(AgentRun)
        .filter(AgentRun.id == run_id, AgentRun.project_id == key.project_id)
        .first()
    )
    if run is None:
        raise AppError("run_not_found", "Run not found.", 404)

    first_seq: int | None = None
    last_seq: int | None = None
    for item in payload.events:
        scrubbed = scrub_telemetry_payload(item.payload)
        serialized = json.dumps(scrubbed, separators=(",", ":"), ensure_ascii=True)
        if len(serialized.encode("utf-8")) > _MAX_TELEMETRY_PAYLOAD_BYTES:
            raise AppError(
                "payload_too_large",
                f"Telemetry payload exceeds {_MAX_TELEMETRY_PAYLOAD_BYTES} bytes.",
                413,
            )
        event = record_event(
            db,
            project_id=key.project_id,
            run_id=run.id,
            kind=item.kind,
            payload_redacted=scrubbed,  # type: ignore[arg-type]
        )
        if first_seq is None:
            first_seq = event.project_seq
        last_seq = event.project_seq
    db.commit()
    return EventIngestResponse(
        run_id=run.id,
        accepted=len(payload.events),
        first_seq=first_seq,
        last_seq=last_seq,
        received_at=utcnow(),
    )
