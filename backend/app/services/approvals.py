"""Supervisor decisions and approval expiry. Every transition is atomic (row lock + state check)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import Principal
from app.core.clock import now_utc
from app.core.errors import conflict, forbidden, not_found
from app.db.models import AgentRun, ApprovalRequest, ProposedAction
from app.services import audit, events, jobs
from app.services.hashing import action_fingerprint

TERMINAL_RUN_STATUSES = {
    "completed",
    "completed_no_action",
    "rejected",
    "failed",
    "cancelled",
    "needs_human_review",
}


@dataclass
class DecisionResult:
    approval: ApprovalRequest
    action: ProposedAction
    changed: bool


def _load_locked(session: Session, tenant_id: uuid.UUID, approval_id: uuid.UUID):
    approval = session.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id, ApprovalRequest.tenant_id == tenant_id)
        .with_for_update()
    )
    if approval is None:  # other tenants' approvals are concealed as 404
        raise not_found("Approval")
    action = session.scalar(select(ProposedAction).where(ProposedAction.id == approval.action_id).with_for_update())
    assert action is not None
    return approval, action


def _expire(session: Session, approval: ApprovalRequest, action: ProposedAction, actor: str) -> None:
    approval.status = "expired"
    action.status = "expired"
    action.status_reason = "approval_expired"
    audit.record(
        session,
        tenant_id=approval.tenant_id,
        actor_type="system",
        actor_id=actor,
        run_id=action.run_id,
        action_id=action.id,
        event_type="approval_expired",
        metadata={"approval_id": str(approval.id)},
    )
    events.emit(
        session,
        tenant_id=approval.tenant_id,
        run_id=action.run_id,
        event_type="approval_expired",
        payload={"approval_id": str(approval.id), "action_id": str(action.id)},
    )


def decide(
    session: Session, principal: Principal, approval_id: uuid.UUID, decision: str, note: str | None
) -> DecisionResult:
    """Approve or reject exactly one persisted action. The request body carries no authority:
    action arguments, amount, tenant and hash all come from the database."""
    if not principal.has_role("supervisor"):
        raise forbidden("Only supervisors can decide approvals")
    approval, action = _load_locked(session, principal.tenant_id, approval_id)
    wanted = "approved" if decision == "approve" else "rejected"

    if approval.status != "pending":
        if approval.status == wanted:
            return DecisionResult(approval, action, changed=False)  # idempotent repeat
        raise conflict(
            "approval_already_decided",
            f"Approval is already {approval.status}",
            {"status": approval.status},
        )

    if approval.expires_at <= now_utc():
        _expire(session, approval, action, actor="approval-service")
        session.flush()
        raise conflict("approval_expired", "Approval has expired; a fresh proposal is required")

    current_hash = action_fingerprint(
        action_type=action.action_type,
        ticket_id=action.ticket_id,
        payload=action.payload,
        policy_version=action.policy_version,
    )
    if current_hash != approval.action_hash or current_hash != action.payload_sha256:
        raise conflict("action_hash_mismatch", "The proposed action changed after it was submitted")

    run = session.get(AgentRun, action.run_id)
    if run is None or run.status in TERMINAL_RUN_STATUSES:
        raise conflict("run_not_active", "The run is no longer waiting for approval")

    approval.status = wanted
    approval.decided_by = principal.user_id
    approval.decided_by_name = principal.username
    approval.decided_at = now_utc()
    approval.decision_note = note
    action.status = wanted
    audit.record(
        session,
        tenant_id=approval.tenant_id,
        actor_type="user",
        actor_id=principal.user_id,
        run_id=action.run_id,
        action_id=action.id,
        event_type=f"approval_{wanted}",
        metadata={"approval_id": str(approval.id), "note": note, "action_hash": approval.action_hash},
    )
    events.emit(
        session,
        tenant_id=approval.tenant_id,
        run_id=action.run_id,
        event_type=f"approval_{wanted}",
        payload={
            "approval_id": str(approval.id),
            "action_id": str(action.id),
            "action_type": action.action_type,
            "decided_by": principal.username or principal.user_id,
        },
    )
    jobs.enqueue(
        session,
        job_type="resume",
        dedupe_key=f"resume:{action.run_id}:{approval.id}",
        run_id=action.run_id,
        tenant_id=approval.tenant_id,
        payload={"approval_id": str(approval.id)},
    )
    session.flush()
    return DecisionResult(approval, action, changed=True)


def expire_due(session: Session) -> int:
    """Flip overdue pending approvals to expired and resume their runs so they can finish."""
    due = list(
        session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= now_utc())
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    )
    for approval in due:
        action = session.scalar(
            select(ProposedAction).where(ProposedAction.id == approval.action_id).with_for_update()
        )
        assert action is not None
        _expire(session, approval, action, actor="expiry-sweeper")
        jobs.enqueue(
            session,
            job_type="resume",
            dedupe_key=f"resume:{action.run_id}:{approval.id}",
            run_id=action.run_id,
            tenant_id=approval.tenant_id,
            payload={"approval_id": str(approval.id), "reason": "expired"},
        )
    session.flush()
    return len(due)
