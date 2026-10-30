"""Append-only audit trail. Always written in the same transaction as the domain change."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent

_REDACT_KEYS = {"token", "access_token", "authorization", "password", "api_key", "secret"}


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def record(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor_type: str,
    actor_id: str,
    event_type: str,
    run_id: uuid.UUID | None = None,
    action_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        run_id=run_id,
        action_id=action_id,
        event_type=event_type,
        metadata_=redact(metadata or {}),
    )
    session.add(event)
    session.flush()
    return event
