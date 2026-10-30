"""Run lifecycle: creation, status transitions, batch fan-out and cancellation."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.core.clock import now_utc
from app.core.config import get_settings
from app.core.errors import AppError, conflict, not_found
from app.db.models import AgentRun, ApprovalRequest, ProposedAction, Ticket
from app.services import audit, events, jobs
from app.services.approvals import TERMINAL_RUN_STATUSES

BATCH_FILTER_KEYS = {"status", "priority", "query"}


def set_status(session: Session, run: AgentRun, status: str, **payload: Any) -> None:
    if run.status == status:
        return
    run.status = status
    if status == "running" and run.started_at is None:
        run.started_at = now_utc()
    if status in TERMINAL_RUN_STATUSES:
        run.finished_at = now_utc()
    events.emit(session, tenant_id=run.tenant_id, run_id=run.id, event_type="status_changed",
                payload={"status": status, **payload})


def _new_run(principal: Principal, *, mode: str, instruction: str, ticket: Ticket | None,
             parent_id: uuid.UUID | None = None, filters: dict | None = None) -> AgentRun:
    run_id = uuid.uuid4()
    return AgentRun(
        id=run_id,
        tenant_id=principal.tenant_id,
        requested_by_user_id=principal.user_id,
        requested_by_name=principal.username,
        parent_run_id=parent_id,
        ticket_id=ticket.id if ticket else None,
        mode=mode,
        original_instruction=instruction,
        batch_filters=filters,
        thread_id=f"run-{run_id}",  # server-derived; never taken from a request
        status="queued",
    )


def _enqueue_start(session: Session, run: AgentRun) -> None:
    jobs.enqueue(session, job_type="start", dedupe_key=f"start:{run.id}", run_id=run.id, tenant_id=run.tenant_id)


def create_ticket_run(session: Session, principal: Principal, ticket_number: str, instruction: str,
                      parent_id: uuid.UUID | None = None) -> AgentRun:
    ticket = session.scalar(
        select(Ticket).where(Ticket.tenant_id == principal.tenant_id, Ticket.ticket_number == ticket_number)
    )
    if ticket is None:
        raise not_found(f"Ticket {ticket_number}")
    run = _new_run(principal, mode="ticket", instruction=instruction, ticket=ticket, parent_id=parent_id)
    session.add(run)
    session.flush()
    events.emit(session, tenant_id=run.tenant_id, run_id=run.id, event_type="run_created",
                payload={"ticket_number": ticket_number, "mode": "ticket"})
    audit.record(session, tenant_id=run.tenant_id, actor_type="user", actor_id=principal.user_id,
                 run_id=run.id, event_type="run_started",
                 metadata={"ticket_number": ticket_number, "instruction": instruction[:500]})
    _enqueue_start(session, run)
    return run


def create_batch_run(session: Session, principal: Principal, instruction: str, filters: dict[str, str] | None,
                     limit: int | None) -> AgentRun:
    settings = get_settings()
    requested = limit or settings.max_batch_tickets
    if requested > settings.max_batch_tickets:
        raise AppError(400, "batch_limit_exceeded",
                       f"Batch runs are limited to {settings.max_batch_tickets} tickets",
                       {"requested": requested, "max": settings.max_batch_tickets})
    clean = {k: v for k, v in (filters or {}).items() if k in BATCH_FILTER_KEYS}
    clean["limit"] = str(requested)
    run = _new_run(principal, mode="batch", instruction=instruction, ticket=None, filters=clean)
    session.add(run)
    session.flush()
    events.emit(session, tenant_id=run.tenant_id, run_id=run.id, event_type="run_created",
                payload={"mode": "batch", "filters": clean})
    audit.record(session, tenant_id=run.tenant_id, actor_type="user", actor_id=principal.user_id,
                 run_id=run.id, event_type="batch_run_started", metadata={"filters": clean})
    _enqueue_start(session, run)
    return run


def fan_out_batch(session: Session, parent: AgentRun) -> list[AgentRun]:
    """Deterministically select tickets (tenant-scoped, server-side) and create one child run each."""
    existing = list(session.scalars(select(AgentRun).where(AgentRun.parent_run_id == parent.id)))
    if existing:
        return existing
    filters = parent.batch_filters or {}
    limit = min(int(filters.get("limit", 10)), get_settings().max_batch_tickets)
    stmt = select(Ticket).where(Ticket.tenant_id == parent.tenant_id)
    if filters.get("status"):
        stmt = stmt.where(Ticket.status == filters["status"])
    if filters.get("priority"):
        stmt = stmt.where(Ticket.priority == filters["priority"])
    if filters.get("query"):
        stmt = stmt.where(Ticket.subject.ilike(f"%{filters['query'][:100]}%"))
    tickets = list(session.scalars(stmt.order_by(Ticket.ticket_number).limit(limit)))
    principal = Principal(user_id=parent.requested_by_user_id, tenant_id=parent.tenant_id,
                          roles=frozenset({"operator"}), username=parent.requested_by_name)
    children = [
        create_ticket_run(session, principal, t.ticket_number, parent.original_instruction, parent_id=parent.id)
        for t in tickets
    ]
    events.emit(session, tenant_id=parent.tenant_id, run_id=parent.id, event_type="batch_fanned_out",
                payload={"child_run_ids": [str(c.id) for c in children],
                         "ticket_numbers": [t.ticket_number for t in tickets]})
    return children


def aggregate_batch_status(children: list[AgentRun]) -> str:
    if not children:
        return "completed_no_action"
    statuses = {c.status for c in children}
    if statuses - TERMINAL_RUN_STATUSES:
        return "awaiting_approval" if "awaiting_approval" in statuses else "running"
    if "completed" in statuses:
        return "completed"
    if statuses <= {"completed_no_action"}:
        return "completed_no_action"
    if "failed" in statuses or "needs_human_review" in statuses:
        return "failed" if statuses <= {"failed"} else "completed"
    return "completed"


def get_run(session: Session, tenant_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id))
    if run is None:
        raise not_found("Run")
    return run


def cancel_run(session: Session, principal: Principal, run_id: uuid.UUID) -> AgentRun:
    run = session.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == principal.tenant_id).with_for_update()
    )
    if run is None:
        raise not_found("Run")
    if run.status in TERMINAL_RUN_STATUSES:
        raise conflict("run_already_finished", f"Run is already {run.status}")
    targets = [run, *session.scalars(select(AgentRun).where(AgentRun.parent_run_id == run.id))]
    for target in targets:
        if target.status in TERMINAL_RUN_STATUSES:
            continue
        pending = session.execute(
            select(ApprovalRequest, ProposedAction)
            .join(ProposedAction, ProposedAction.id == ApprovalRequest.action_id)
            .where(ProposedAction.run_id == target.id, ApprovalRequest.status == "pending")
            .with_for_update()
        ).all()
        for approval, action in pending:
            approval.status = "expired"
            approval.decision_note = "run cancelled"
            action.status = "expired"
            action.status_reason = "run_cancelled"
        jobs.cancel_for_run(session, target.id)
        set_status(session, target, "cancelled")
        audit.record(session, tenant_id=target.tenant_id, actor_type="user", actor_id=principal.user_id,
                     run_id=target.id, event_type="run_cancelled", metadata={})
    session.flush()
    return run
