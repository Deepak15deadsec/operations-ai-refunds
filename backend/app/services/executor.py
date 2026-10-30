"""Idempotent executor for approved actions. The only code that creates simulated side effects.

Each call runs inside the caller's transaction: lock rows, re-verify approval and fresh domain
state, write the effect + audit event, and let the caller commit. Re-running after a crash finds
the recorded effect and returns it instead of writing again.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.db.models import (
    ApprovalRequest,
    Customer,
    Order,
    OutboundMessage,
    ProposedAction,
    Refund,
    RefundPolicy,
    Ticket,
)
from app.services import audit, events
from app.services.hashing import action_fingerprint
from app.services.policy import PolicyService


@dataclass(frozen=True)
class ExecutionOutcome:
    action_id: uuid.UUID
    status: str  # completed | failed | skipped
    reason: str | None = None
    effect_id: uuid.UUID | None = None
    already_done: bool = False


class _Refuse(Exception):
    def __init__(self, reason: str):
        self.reason = reason


def _fail(session: Session, action: ProposedAction, reason: str, status: str = "failed") -> ExecutionOutcome:
    action.status = status
    action.status_reason = reason
    audit.record(
        session,
        tenant_id=action.tenant_id,
        actor_type="system",
        actor_id="executor",
        run_id=action.run_id,
        action_id=action.id,
        event_type="action_execution_blocked",
        metadata={"reason": reason, "action_type": action.action_type},
    )
    events.emit(
        session,
        tenant_id=action.tenant_id,
        run_id=action.run_id,
        event_type="action_failed",
        payload={"action_id": str(action.id), "action_type": action.action_type, "reason": reason},
    )
    session.flush()
    return ExecutionOutcome(action.id, "failed", reason)


def _existing_effect(session: Session, action: ProposedAction) -> uuid.UUID | None:
    if action.action_type == "refund":
        return session.scalar(select(Refund.id).where(Refund.action_id == action.id))
    if action.action_type == "send_reply":
        return session.scalar(select(OutboundMessage.id).where(OutboundMessage.action_id == action.id))
    return None


def _verify_approval(session: Session, action: ProposedAction) -> None:
    approval = session.scalar(
        select(ApprovalRequest).where(ApprovalRequest.action_id == action.id).with_for_update()
    )
    if approval is None or approval.status != "approved":
        raise _Refuse("not_approved")
    if approval.decided_at is None or approval.decided_at > approval.expires_at:
        raise _Refuse("approval_expired")
    fingerprint = action_fingerprint(
        action_type=action.action_type,
        ticket_id=action.ticket_id,
        payload=action.payload,
        policy_version=action.policy_version,
    )
    if fingerprint != approval.action_hash or fingerprint != action.payload_sha256:
        raise _Refuse("action_hash_mismatch")


def _execute_refund(session: Session, action: ProposedAction) -> uuid.UUID:
    payload = action.payload
    order = session.scalar(
        select(Order)
        .where(Order.tenant_id == action.tenant_id, Order.order_number == payload["order_number"])
        .with_for_update()
    )
    ticket = session.get(Ticket, action.ticket_id)
    if order is None or ticket is None or ticket.order_id != order.id:
        raise _Refuse("order_not_linked_to_ticket")
    policy = session.scalar(
        select(RefundPolicy).where(RefundPolicy.tenant_id == action.tenant_id, RefundPolicy.active.is_(True))
    )
    if policy is None or policy.version != action.policy_version:
        raise _Refuse("policy_changed")
    refunded = bool(session.scalar(select(exists().where(Refund.order_id == order.id))))
    if refunded:
        raise _Refuse("already_refunded")
    evaluation = PolicyService.evaluate_refund(order, policy, now_utc(), already_refunded=False)
    if not evaluation.eligible:
        raise _Refuse("no_longer_eligible")
    if payload["amount_minor"] != evaluation.max_amount_minor or payload["currency"] != order.currency:
        raise _Refuse("amount_mismatch")

    refund = Refund(
        id=uuid.uuid4(),
        tenant_id=action.tenant_id,
        order_id=order.id,
        action_id=action.id,
        idempotency_key=f"refund:{action.id}",
        amount_minor=payload["amount_minor"],
        currency=payload["currency"],
        status="simulated_success",
    )
    try:
        with session.begin_nested():  # unique constraints are the final guard against races
            session.add(refund)
            session.flush()
    except IntegrityError as exc:
        raise _Refuse("already_refunded") from exc
    return refund.id


def _execute_reply(session: Session, action: ProposedAction) -> uuid.UUID:
    ticket = session.get(Ticket, action.ticket_id)
    customer = session.get(Customer, ticket.customer_id) if ticket else None
    if customer is None or customer.email != action.payload["destination"]:
        raise _Refuse("destination_changed")
    message = OutboundMessage(
        id=uuid.uuid4(),
        tenant_id=action.tenant_id,
        ticket_id=action.ticket_id,
        action_id=action.id,
        idempotency_key=f"message:{action.id}",
        destination=customer.email,
        body=action.payload["message_body"],
        status="simulated_sent",
    )
    try:
        with session.begin_nested():
            session.add(message)
            session.flush()
    except IntegrityError as exc:
        raise _Refuse("duplicate_message") from exc
    return message.id


def _execute_escalation(session: Session, action: ProposedAction) -> uuid.UUID:
    ticket = session.scalar(select(Ticket).where(Ticket.id == action.ticket_id).with_for_update())
    if ticket is None or ticket.status not in ("open", "pending"):
        raise _Refuse("invalid_ticket_transition")
    ticket.status = "escalated"
    session.flush()
    return ticket.id


_HANDLERS = {"refund": _execute_refund, "send_reply": _execute_reply, "escalate_ticket": _execute_escalation}


def execute_action(session: Session, action_id: uuid.UUID) -> ExecutionOutcome:
    action = session.scalar(select(ProposedAction).where(ProposedAction.id == action_id).with_for_update())
    if action is None:
        return ExecutionOutcome(action_id, "skipped", "not_found")

    if action.status == "completed":
        return ExecutionOutcome(action.id, "completed", effect_id=_existing_effect(session, action), already_done=True)
    if action.status != "approved":
        return ExecutionOutcome(action.id, "skipped", action.status_reason or action.status)

    # Crash after a committed effect but before the status update cannot happen (same transaction),
    # but check anyway so a manual status repair can never cause a second effect.
    effect_id = _existing_effect(session, action)
    if effect_id is None:
        try:
            _verify_approval(session, action)
            effect_id = _HANDLERS[action.action_type](session, action)
        except _Refuse as refusal:
            status = "needs_review" if refusal.reason in ("policy_changed", "destination_changed") else "failed"
            return _fail(session, action, refusal.reason, status=status)

    action.status = "completed"
    action.status_reason = None
    audit.record(
        session,
        tenant_id=action.tenant_id,
        actor_type="system",
        actor_id="executor",
        run_id=action.run_id,
        action_id=action.id,
        event_type=f"{action.action_type}_executed",
        metadata={"effect_id": str(effect_id), "payload": action.payload, "simulated": True},
    )
    events.emit(
        session,
        tenant_id=action.tenant_id,
        run_id=action.run_id,
        event_type="action_executed",
        payload={"action_id": str(action.id), "action_type": action.action_type, "effect_id": str(effect_id)},
    )
    session.flush()
    return ExecutionOutcome(action.id, "completed", effect_id=effect_id)
