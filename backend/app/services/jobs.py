"""PostgreSQL-backed job queue with leases and `FOR UPDATE SKIP LOCKED`."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.config import get_settings
from app.db.models import WorkerJob


def enqueue(
    session: Session,
    *,
    job_type: str,
    dedupe_key: str,
    run_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    delay_seconds: float = 0,
) -> bool:
    """Insert a job unless one with the same dedupe key exists. Returns True if inserted."""
    stmt = (
        insert(WorkerJob)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            run_id=run_id,
            job_type=job_type,
            dedupe_key=dedupe_key,
            payload=payload or {},
            status="queued",
            attempts=0,
            max_attempts=get_settings().job_max_attempts,
            available_at=now_utc() + timedelta(seconds=delay_seconds),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    result = session.execute(stmt)
    return bool(result.rowcount)  # type: ignore[attr-defined]


# Claims one runnable job. A job is runnable if queued and due, or leased with an expired lease
# (crashed worker). Jobs for a run that has another live leased job are skipped, which serialises
# work per run (e.g. a resume job never runs concurrently with the run's start job).
_CLAIM_SQL = text(
    """
    WITH candidate AS (
        SELECT j.id FROM worker_jobs j
        WHERE (
            (j.status = 'queued' AND j.available_at <= :now)
            OR (j.status = 'leased' AND j.leased_until < :now)
        )
        AND NOT EXISTS (
            SELECT 1 FROM worker_jobs other
            WHERE other.run_id = j.run_id AND other.id <> j.id
              AND other.status = 'leased' AND other.leased_until >= :now
        )
        ORDER BY j.available_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE worker_jobs w
    SET status = 'leased', lease_owner = :owner, leased_until = :until,
        attempts = w.attempts + 1, updated_at = now()
    FROM candidate WHERE w.id = candidate.id
    RETURNING w.id
    """
)


def claim(session: Session, owner: str, lease_seconds: int | None = None) -> WorkerJob | None:
    now = now_utc()
    lease = lease_seconds or get_settings().worker_lease_seconds
    job_id = session.execute(
        _CLAIM_SQL, {"now": now, "owner": owner, "until": now + timedelta(seconds=lease)}
    ).scalar()
    if job_id is None:
        return None
    return session.get(WorkerJob, job_id)


def extend_lease(session: Session, job_id: uuid.UUID, owner: str, lease_seconds: int) -> bool:
    result = session.execute(
        text(
            "UPDATE worker_jobs SET leased_until = :until WHERE id = :id AND lease_owner = :owner "
            "AND status = 'leased'"
        ),
        {"until": now_utc() + timedelta(seconds=lease_seconds), "id": job_id, "owner": owner},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def complete(session: Session, job_id: uuid.UUID, owner: str) -> None:
    session.execute(
        text(
            "UPDATE worker_jobs SET status = 'done', leased_until = NULL, updated_at = now() "
            "WHERE id = :id AND lease_owner = :owner"
        ),
        {"id": job_id, "owner": owner},
    )


def reschedule(session: Session, job_id: uuid.UUID, owner: str, delay_seconds: float, *, consume: bool) -> None:
    """Put a job back in the queue. `consume=False` refunds the attempt (used for 'not ready yet')."""
    session.execute(
        text(
            "UPDATE worker_jobs SET status = 'queued', lease_owner = NULL, leased_until = NULL, "
            "available_at = :at, attempts = attempts - :refund, updated_at = now() "
            "WHERE id = :id AND lease_owner = :owner"
        ),
        {
            "id": job_id,
            "owner": owner,
            "at": now_utc() + timedelta(seconds=delay_seconds),
            "refund": 0 if consume else 1,
        },
    )


def fail(session: Session, job_id: uuid.UUID, owner: str, error: str) -> None:
    session.execute(
        text(
            "UPDATE worker_jobs SET status = 'failed', last_error = :err, leased_until = NULL, "
            "updated_at = now() WHERE id = :id AND lease_owner = :owner"
        ),
        {"id": job_id, "owner": owner, "err": error[:2000]},
    )


def record_error(session: Session, job_id: uuid.UUID, error: str) -> None:
    session.execute(
        text("UPDATE worker_jobs SET last_error = :err WHERE id = :id"), {"id": job_id, "err": error[:2000]}
    )


def cancel_for_run(session: Session, run_id: uuid.UUID) -> None:
    session.execute(
        text("UPDATE worker_jobs SET status = 'cancelled' WHERE run_id = :run AND status = 'queued'"),
        {"run": run_id},
    )
