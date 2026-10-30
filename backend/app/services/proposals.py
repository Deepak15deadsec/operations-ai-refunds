"""Validate agent proposals against deterministic rules and persist actions + approval requests.

Nothing here performs a side effect. Valid actions become `pending_approval`; invalid ones are
recorded as `failed` with an explicit `status_reason` so the operator can see why.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.config import get_settings
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    Customer,
    Order,
    ProposedAction,
    Refund,
    Ticket,
)
from app.schemas.investigation import (
    EscalateTicketProposal,
    InvestigationResult,
    NoActionProposal,
    RefundProposal,
    SendReplyProposal,
)
from app.services import audit, events
from app.services.hashing import action_fingerprint
from app.services.policy import PolicyService
from app.services.read_service import active_policy_row

MAX_REPLY_CHARS = 2000
# Claims a simulated system must never make to a customer.
FORBIDDEN_REPLY_PHRASES = ("has been transferred", "money has been sent", "password", "otp")


@dataclass
class Validated:
    action_type: str
    payload: dict[str, Any]
    reason: str
    policy_version: str | None
    ok: bool
    status_reason: str | None
    backend_evidence: dict[str, Any] | None = None


def _validate_refund(session: Session, ticket: Ticket, p: RefundProposal) -> Validated:
    order = session.scalar(
        select(Order).where(Order.tenant_id == ticket.tenant_id, Order.order_number == p.order_number)
    )
    payload = {"order_number": p.order_number, "amount_minor": p.amount_minor, "currency": p.currency}
    if order is None:
        return Validated("refund", payload, p.reason, None, False, "order_not_found")
    if ticket.order_id != order.id:
        return Validated("refund", payload, p.reason, None, False, "order_not_linked_to_ticket")
    policy = active_policy_row(session, ticket.tenant_id)
    refunded = bool(session.scalar(select(exists().where(Refund.order_id == order.id))))
    evaluation = PolicyService.evaluate_refund(order, policy, now_utc(), already_refunded=refunded)
    evidence = {"source_type": "policy_evaluation", "source_id": policy.version, **evaluation.to_dict()}
    if not evaluation.eligible:
        return Validated("refund", payload, p.reason, policy.version, False, "policy_ineligible", evidence)
    if p.currency != order.currency:
        return Validated("refund", payload, p.reason, policy.version, False, "currency_mismatch", evidence)
    if p.amount_minor != evaluation.max_amount_minor:
        return Validated("refund", payload, p.reason, policy.version, False, "amount_mismatch", evidence)
    return Validated("refund", payload, p.reason, policy.version, True, None, evidence)


def _validate_reply(session: Session, ticket: Ticket, p: SendReplyProposal) -> Validated:
    customer = session.get(Customer, ticket.customer_id)
    body = p.message_body.strip()
    payload = {
        "ticket_number": p.ticket_number,
        "destination": customer.email if customer else None,
        "message_body": body,
    }
    if p.ticket_number != ticket.ticket_number:
        return Validated("send_reply", payload, p.reason, None, False, "ticket_mismatch")
    if not body or len(body) > MAX_REPLY_CHARS:
        return Validated("send_reply", payload, p.reason, None, False, "invalid_message_length")
    if any(phrase in body.lower() for phrase in FORBIDDEN_REPLY_PHRASES):
        return Validated("send_reply", payload, p.reason, None, False, "forbidden_message_content")
    if customer is None:
        return Validated("send_reply", payload, p.reason, None, False, "no_destination")
    return Validated("send_reply", payload, p.reason, None, True, None)


def _validate_escalation(ticket: Ticket, p: EscalateTicketProposal) -> Validated:
    payload = {"ticket_number": p.ticket_number, "from_status": ticket.status}
    if p.ticket_number != ticket.ticket_number:
        return Validated("escalate_ticket", payload, p.reason, None, False, "ticket_mismatch")
    if ticket.status not in ("open", "pending"):
        return Validated("escalate_ticket", payload, p.reason, None, False, "invalid_ticket_transition")
    return Validated("escalate_ticket", payload, p.reason, None, True, None)


def validate(session: Session, ticket: Ticket, result: InvestigationResult) -> list[Validated]:
    seen: set[str] = set()
    out: list[Validated] = []
    for proposal in result.proposals:
        if isinstance(proposal, NoActionProposal):
            continue
        if proposal.action_type in seen:  # one action of each type per run
            continue
        seen.add(proposal.action_type)
        if isinstance(proposal, RefundProposal):
            out.append(_validate_refund(session, ticket, proposal))
        elif isinstance(proposal, SendReplyProposal):
            out.append(_validate_reply(session, ticket, proposal))
        elif isinstance(proposal, EscalateTicketProposal):
            out.append(_validate_escalation(ticket, proposal))
    return out


def persist(
    session: Session, run: AgentRun, ticket: Ticket, result: InvestigationResult, validated: list[Validated]
) -> list[ProposedAction]:
    """Idempotent: if this run already has actions (node re-run after a crash), return them."""
    existing = list(session.scalars(select(ProposedAction).where(ProposedAction.run_id == run.id)))
    if existing:
        return existing

    settings = get_settings()
    findings = [f.model_dump() for f in result.findings]
    actions: list[ProposedAction] = []
    for v in validated:
        evidence = findings + ([v.backend_evidence] if v.backend_evidence else [])
        action = ProposedAction(
            id=uuid.uuid4(),
            tenant_id=run.tenant_id,
            run_id=run.id,
            ticket_id=ticket.id,
            action_type=v.action_type,
            payload=v.payload,
            payload_sha256=action_fingerprint(
                action_type=v.action_type, ticket_id=ticket.id, payload=v.payload, policy_version=v.policy_version
            ),
            policy_version=v.policy_version,
            status="pending_approval" if v.ok else "failed",
            status_reason=v.status_reason,
            reason=v.reason,
            evidence=evidence,
        )
        session.add(action)
        session.flush()
        audit.record(
            session,
            tenant_id=run.tenant_id,
            actor_type="agent",
            actor_id=f"run:{run.id}",
            run_id=run.id,
            action_id=action.id,
            event_type="action_proposed" if v.ok else "action_rejected_by_validation",
            metadata={"action_type": v.action_type, "payload": v.payload, "status_reason": v.status_reason},
        )
        events.emit(
            session,
            tenant_id=run.tenant_id,
            run_id=run.id,
            event_type="action_proposed" if v.ok else "action_invalid",
            payload={
                "action_id": str(action.id),
                "action_type": v.action_type,
                "status_reason": v.status_reason,
            },
        )
        if v.ok:
            approval = ApprovalRequest(
                id=uuid.uuid4(),
                tenant_id=run.tenant_id,
                action_id=action.id,
                status="pending",
                requested_by=run.requested_by_user_id,
                expires_at=now_utc() + timedelta(hours=settings.approval_ttl_hours),
                action_hash=action.payload_sha256,
            )
            session.add(approval)
            session.flush()
            audit.record(
                session,
                tenant_id=run.tenant_id,
                actor_type="system",
                actor_id="approval-service",
                run_id=run.id,
                action_id=action.id,
                event_type="approval_requested",
                metadata={"approval_id": str(approval.id), "expires_at": approval.expires_at.isoformat()},
            )
            events.emit(
                session,
                tenant_id=run.tenant_id,
                run_id=run.id,
                event_type="approval_requested",
                payload={
                    "approval_id": str(approval.id),
                    "action_id": str(action.id),
                    "action_type": v.action_type,
                },
            )
        actions.append(action)
    return actions
