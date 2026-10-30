"""Durable run events (the SSE source). Persisted first, then NOTIFY on commit."""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import AgentEvent
from app.services.audit import redact

NOTIFY_CHANNEL = "agent_events"


def emit(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID, event_type: str, payload: dict[str, Any]
) -> AgentEvent:
    event = AgentEvent(tenant_id=tenant_id, run_id=run_id, event_type=event_type, payload=redact(payload))
    session.add(event)
    session.flush()
    # Delivered only if/when the surrounding transaction commits.
    session.execute(text("SELECT pg_notify(:channel, :run_id)"), {"channel": NOTIFY_CHANNEL, "run_id": str(run_id)})
    return event


def list_after(
    session: Session, *, tenant_id: uuid.UUID, run_ids: list[uuid.UUID], after_id: int, limit: int = 500
) -> list[AgentEvent]:
    stmt = (
        select(AgentEvent)
        .where(AgentEvent.tenant_id == tenant_id, AgentEvent.run_id.in_(run_ids), AgentEvent.id > after_id)
        .order_by(AgentEvent.id)
        .limit(limit)
    )
    return list(session.scalars(stmt))
