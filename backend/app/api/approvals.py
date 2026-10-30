"""Approval queue and supervisor decisions."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_supervisor
from app.core.errors import not_found
from app.db.models import AgentRun, ApprovalRequest, ProposedAction, Ticket
from app.db.session import get_db
from app.schemas.api import ApprovalOut, DecisionRequest
from app.services import approvals

router = APIRouter(prefix="/api/v1/approvals")


def _out(approval: ApprovalRequest, action: ProposedAction, ticket: Ticket, requester: str | None) -> ApprovalOut:
    return ApprovalOut(
        approval_id=approval.id,
        action_id=action.id,
        run_id=action.run_id,
        ticket_number=ticket.ticket_number,
        ticket_subject=ticket.subject,
        order_number=action.payload.get("order_number"),
        action_type=action.action_type,
        payload=action.payload,
        reason=action.reason,
        evidence=action.evidence,
        policy_version=action.policy_version,
        status=approval.status,
        action_status=action.status,
        action_status_reason=action.status_reason,
        action_hash=approval.action_hash,
        requested_by=approval.requested_by,
        requested_by_name=requester,
        decided_by=approval.decided_by,
        decided_by_name=approval.decided_by_name,
        decided_at=approval.decided_at,
        decision_note=approval.decision_note,
        created_at=approval.created_at,
        expires_at=approval.expires_at,
    )


def _query(tenant_id: uuid.UUID):
    return (
        select(ApprovalRequest, ProposedAction, Ticket, AgentRun.requested_by_name)
        .join(ProposedAction, ProposedAction.id == ApprovalRequest.action_id)
        .join(Ticket, Ticket.id == ProposedAction.ticket_id)
        .join(AgentRun, AgentRun.id == ProposedAction.run_id)
        .where(ApprovalRequest.tenant_id == tenant_id)
    )


@router.get("", response_model=list[ApprovalOut])
def list_approvals(
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected|expired)$"),
    run_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_supervisor),
    db: Session = Depends(get_db),
):
    stmt = _query(principal.tenant_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    if run_id:
        stmt = stmt.where(ProposedAction.run_id == run_id)
    rows = db.execute(stmt.order_by(ApprovalRequest.created_at.desc()).limit(limit)).all()
    return [_out(*row) for row in rows]


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: uuid.UUID, principal: Principal = Depends(require_supervisor),
                 db: Session = Depends(get_db)):
    row = db.execute(_query(principal.tenant_id).where(ApprovalRequest.id == approval_id)).first()
    if row is None:
        raise not_found("Approval")
    return _out(*row)


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
def decide(approval_id: uuid.UUID, body: DecisionRequest, principal: Principal = Depends(require_supervisor),
           db: Session = Depends(get_db)):
    result = approvals.decide(db, principal, approval_id, body.decision, body.note)
    ticket = db.get(Ticket, result.action.ticket_id)
    run = db.get(AgentRun, result.action.run_id)
    assert ticket is not None and run is not None
    return _out(result.approval, result.action, ticket, run.requested_by_name)
