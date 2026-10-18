"""Durable event + outbox recording (M08).

`record_event` inserts an `events` row and its `outbox` row and flushes them;
the caller owns the transaction and commits. Payloads must already be
redacted — this module never sees raw tool arguments.

Every event is assigned a per-project monotonic `project_seq`, which is the
SSE `Last-Event-ID` cursor contract. Assignment is atomic: the project's
counter row is locked (`SELECT ... FOR UPDATE`) inside the caller's
transaction, so concurrent recorders in the same project can never hand out
the same sequence number. The counter row is created idempotently with
`ON CONFLICT DO NOTHING` to survive races on first use.

Outbox role (Phase 8 audit MEDIUM-5, honest scope): the `outbox` table is
currently an audit trail of "events eligible for external publication".
No publisher worker exists yet — the SSE stream reads `events` directly —
so `published_at` is never set by this codebase. `prune_old_events`
enforces the retention window; a real publisher is future work.
"""

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import Event, Outbox, ProjectEventSeq
from .util import utcnow


def new_event_id() -> str:
    """Stable, unique event identifier."""
    return f"evt_{uuid.uuid4().hex}"


def _next_project_seq(db: Session, project_id: UUID) -> int:
    """Atomically claim the next per-project event sequence number.

    Must be called inside the caller's transaction; the row lock serializes
    concurrent event recorders for the same project.
    """
    db.execute(
        pg_insert(ProjectEventSeq)
        .values(project_id=project_id, next_seq=1)
        .on_conflict_do_nothing(index_elements=["project_id"])
    )
    counter = (
        db.query(ProjectEventSeq)
        .filter(ProjectEventSeq.project_id == project_id)
        .with_for_update()
        .one()
    )
    seq = counter.next_seq
    counter.next_seq = seq + 1
    db.flush()
    return seq


def record_event(
    db: Session,
    *,
    project_id: UUID,
    run_id: UUID | None,
    kind: str,
    payload_redacted: dict[str, Any],
) -> Event:
    """Persist one event and its outbox row. Flushes; does NOT commit."""
    event = Event(
        event_id=new_event_id(),
        project_id=project_id,
        run_id=run_id,
        project_seq=_next_project_seq(db, project_id),
        kind=kind,
        payload_redacted=payload_redacted,
        received_at=utcnow(),
    )
    db.add(event)
    db.flush()  # assign seq
    db.add(
        Outbox(
            event_id=event.event_id,
            published_at=None,
            retries=0,
            next_attempt_at=utcnow(),
        )
    )
    db.flush()
    return event


def prune_old_events(db: Session, *, retention_days: int) -> int:
    """Delete events (and their outbox rows via cascade) older than the window.

    Phase 8 audit MEDIUM-5: wires `AGENTTRUST_EVENT_RETENTION_DAYS` to a
    real cleanup so the events table does not grow unboundedly. Returns the
    number of events deleted. The caller owns the commit.
    """
    from datetime import timedelta

    from .util import utcnow

    cutoff = utcnow() - timedelta(days=retention_days)
    deleted = (
        db.query(Event)
        .filter(Event.received_at < cutoff)
        .delete(synchronize_session=False)
    )
    return deleted
