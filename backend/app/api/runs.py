"""Run endpoints, including the SSE event stream (replay + live follow)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import psycopg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import enforce_run_rate_limit
from app.core.auth import Principal, require_operator
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AgentRun, ApprovalRequest, ProposedAction, Ticket
from app.db.session import get_db, transaction
from app.schemas.api import (
    ActionOut,
    ApprovalSummary,
    RunDetailOut,
    RunOut,
    StartRunRequest,
    StartRunResponse,
)
from app.services import events, runs
from app.services.approvals import TERMINAL_RUN_STATUSES
from app.services.events import NOTIFY_CHANNEL

router = APIRouter(prefix="/api/v1/runs")
HEARTBEAT_SECONDS = 15
FALLBACK_POLL_SECONDS = 2.0


def _run_out(db: Session, run: AgentRun) -> RunOut:
    ticket_number = db.scalar(select(Ticket.ticket_number).where(Ticket.id == run.ticket_id)) if run.ticket_id \
        else None
    return RunOut(run_id=run.id, mode=run.mode, status=run.status, ticket_number=ticket_number,
                  parent_run_id=run.parent_run_id, original_instruction=run.original_instruction,
                  requested_by_user_id=run.requested_by_user_id,
                  requested_by_name=run.requested_by_name, error_code=run.error_code,
                  error_message=run.error_message, created_at=run.created_at, started_at=run.started_at,
                  finished_at=run.finished_at)


@router.post("", status_code=202, response_model=StartRunResponse)
def start_run(body: StartRunRequest, principal: Principal = Depends(require_operator),
              db: Session = Depends(get_db)):
    enforce_run_rate_limit(principal)
    if body.mode == "ticket":
        if not body.ticket_number:
            raise AppError(400, "ticket_number_required", "ticket_number is required for ticket mode")
        run = runs.create_ticket_run(db, principal, body.ticket_number, body.instruction)
    else:
        run = runs.create_batch_run(db, principal, body.instruction, body.filters, body.limit)
    return StartRunResponse(run_id=run.id, status=run.status, events_url=f"/api/v1/runs/{run.id}/events")


@router.get("", response_model=list[RunOut])
def list_runs(principal: Principal = Depends(require_operator), db: Session = Depends(get_db),
              limit: int = Query(default=50, ge=1, le=200), top_level: bool = True):
    stmt = select(AgentRun).where(AgentRun.tenant_id == principal.tenant_id)
    if top_level:
        stmt = stmt.where(AgentRun.parent_run_id.is_(None))
    return [_run_out(db, r) for r in db.scalars(stmt.order_by(AgentRun.created_at.desc()).limit(limit))]


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(run_id: uuid.UUID, principal: Principal = Depends(require_operator), db: Session = Depends(get_db)):
    run = runs.get_run(db, principal.tenant_id, run_id)
    rows = db.execute(
        select(ProposedAction, ApprovalRequest)
        .outerjoin(ApprovalRequest, ApprovalRequest.action_id == ProposedAction.id)
        .where(ProposedAction.run_id == run.id).order_by(ProposedAction.created_at)
    ).all()
    actions = [
        ActionOut(action_id=a.id, action_type=a.action_type, payload=a.payload, status=a.status,
                  status_reason=a.status_reason, reason=a.reason, evidence=a.evidence,
                  policy_version=a.policy_version,
                  approval=ApprovalSummary(approval_id=ap.id, action_id=a.id, action_type=a.action_type,
                                           status=ap.status, action_status=a.status) if ap else None)
        for a, ap in rows
    ]
    children = list(db.scalars(select(AgentRun).where(AgentRun.parent_run_id == run.id)
                               .order_by(AgentRun.created_at)))
    base = _run_out(db, run)
    return RunDetailOut(**base.model_dump(), findings=run.findings, summary=run.summary, usage=run.usage,
                        actions=actions, children=[_run_out(db, c) for c in children])


@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel(run_id: uuid.UUID, principal: Principal = Depends(require_operator), db: Session = Depends(get_db)):
    run = runs.cancel_run(db, principal, run_id)
    return _run_out(db, run)


def _scope(tenant_id: uuid.UUID, run_id: uuid.UUID) -> tuple[list[uuid.UUID], bool]:
    """Run ids whose events belong in this stream (a batch includes its children) + whether all finished."""
    with transaction() as session:
        run = runs.get_run(session, tenant_id, run_id)
        ids = [run.id]
        finished = run.status in TERMINAL_RUN_STATUSES
        for child in session.scalars(select(AgentRun).where(AgentRun.parent_run_id == run.id)):
            ids.append(child.id)
            finished = finished and child.status in TERMINAL_RUN_STATUSES
        return ids, finished


def _fetch(tenant_id: uuid.UUID, run_ids: list[uuid.UUID], after_id: int) -> list[tuple[int, str, dict]]:
    with transaction() as session:
        return [(e.id, e.event_type, {"run_id": str(e.run_id), **e.payload, "created_at": e.created_at.isoformat()})
                for e in events.list_after(session, tenant_id=tenant_id, run_ids=run_ids, after_id=after_id)]


def _format(event_id: int, event_type: str, data: dict) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    principal: Principal = Depends(require_operator),
):
    # Authorise before streaming: unknown or other-tenant runs are a 404.
    run_ids, _ = await run_in_threadpool(_scope, principal.tenant_id, run_id)
    header = request.headers.get("last-event-id")
    last_id = int(header) if header and header.isdigit() else (after or 0)
    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")

    async def generate() -> AsyncIterator[str]:
        nonlocal last_id, run_ids
        yield "retry: 3000\n\n"
        listener = None
        try:
            try:
                listener = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
                await listener.execute(f"LISTEN {NOTIFY_CHANNEL}")
            except psycopg.Error:
                listener = None  # fall back to polling only
            idle = 0.0
            while not await request.is_disconnected():
                batch = await run_in_threadpool(_fetch, principal.tenant_id, run_ids, last_id)
                for event_id, event_type, data in batch:
                    last_id = event_id
                    yield _format(event_id, event_type, data)
                if batch:
                    idle = 0.0
                    if any(t == "batch_fanned_out" for _, t, _ in batch):
                        run_ids, _ = await run_in_threadpool(_scope, principal.tenant_id, run_id)
                    continue
                run_ids, finished = await run_in_threadpool(_scope, principal.tenant_id, run_id)
                if finished:
                    tail = await run_in_threadpool(_fetch, principal.tenant_id, run_ids, last_id)
                    for event_id, event_type, data in tail:
                        last_id = event_id
                        yield _format(event_id, event_type, data)
                    yield "event: stream_end\ndata: {}\n\n"
                    return
                if listener is not None:
                    async for _ in listener.notifies(timeout=FALLBACK_POLL_SECONDS, stop_after=1):
                        pass
                else:
                    await asyncio.sleep(FALLBACK_POLL_SECONDS)
                idle += FALLBACK_POLL_SECONDS
                if idle >= HEARTBEAT_SECONDS:
                    idle = 0.0
                    yield ": heartbeat\n\n"
        finally:
            if listener is not None:
                await listener.close()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
