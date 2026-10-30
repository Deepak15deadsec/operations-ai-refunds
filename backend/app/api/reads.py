"""Ticket, order, policy, ledger, audit and overview endpoints (all tenant-scoped reads)."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.auth import Principal, require_admin, require_operator
from app.core.clock import now_utc
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    DeliveryEvent,
    Order,
    OutboundMessage,
    Refund,
    Ticket,
)
from app.db.session import get_db
from app.schemas.api import (
    AuditEventOut,
    DeliveryEventOut,
    MeOut,
    MessageOut,
    OrderDetailOut,
    OverviewOut,
    Page,
    PolicyOut,
    RefundOut,
    TicketDetailOut,
    TicketOut,
)
from app.services import read_service

router = APIRouter(prefix="/api/v1")


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(require_operator)):
    return MeOut(user_id=principal.user_id, username=principal.username, tenant_id=principal.tenant_id,
                 roles=sorted(principal.roles))


@router.get("/overview", response_model=OverviewOut)
def overview(principal: Principal = Depends(require_operator), db: Session = Depends(get_db)):
    t = principal.tenant_id
    since = now_utc() - timedelta(hours=24)
    count = lambda stmt: db.scalar(stmt) or 0  # noqa: E731
    return OverviewOut(
        open_tickets=count(select(func.count()).select_from(Ticket).where(Ticket.tenant_id == t,
                                                                           Ticket.status == "open")),
        high_priority_open_tickets=count(select(func.count()).select_from(Ticket).where(
            Ticket.tenant_id == t, Ticket.status == "open", Ticket.priority.in_(["high", "urgent"]))),
        pending_approvals=count(select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.tenant_id == t, ApprovalRequest.status == "pending")),
        runs_today=count(select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == t,
                                                                          AgentRun.created_at >= since)),
        simulated_refunds=count(select(func.count()).select_from(Refund).where(Refund.tenant_id == t)),
        simulated_refund_total_minor=count(select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
            Refund.tenant_id == t)),
    )


@router.get("/tickets", response_model=Page[TicketOut])
def list_tickets(
    status: str | None = None,
    priority: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=20),
    cursor: str | None = None,
    principal: Principal = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return read_service.list_tickets(db, principal.tenant_id, status=status, priority=priority, query=q,
                                     limit=limit, cursor=cursor)


def _order_out(db: Session, order: Order) -> dict:
    data = read_service.order_dict(db, order)
    data.pop("days_past_promised_delivery", None)
    return data


@router.get("/tickets/{ticket_number}", response_model=TicketDetailOut)
def get_ticket(ticket_number: str, principal: Principal = Depends(require_operator),
               db: Session = Depends(get_db)):
    ticket = read_service.get_ticket(db, principal.tenant_id, ticket_number)
    order = None
    if ticket["order_number"]:
        order = _order_out(db, read_service.order_row(db, principal.tenant_id, ticket["order_number"]))
    return {**ticket, "order": order}


@router.get("/orders/{order_number}", response_model=OrderDetailOut)
def get_order(order_number: str, principal: Principal = Depends(require_operator), db: Session = Depends(get_db)):
    order = read_service.order_row(db, principal.tenant_id, order_number)
    deliveries = db.scalars(select(DeliveryEvent).where(DeliveryEvent.order_id == order.id)
                            .order_by(DeliveryEvent.event_time))
    return {**_order_out(db, order), "delivery_events": [DeliveryEventOut.model_validate(e) for e in deliveries]}


@router.get("/policies/active", response_model=PolicyOut)
def active_policy(principal: Principal = Depends(require_operator), db: Session = Depends(get_db)):
    return read_service.active_policy_row(db, principal.tenant_id)


@router.get("/refunds", response_model=list[RefundOut])
def refunds(principal: Principal = Depends(require_operator), db: Session = Depends(get_db),
            limit: int = Query(default=100, ge=1, le=500)):
    rows = db.execute(
        select(Refund, Order.order_number).join(Order, Order.id == Refund.order_id)
        .where(Refund.tenant_id == principal.tenant_id).order_by(Refund.created_at.desc()).limit(limit)
    ).all()
    return [RefundOut(refund_id=r.id, order_number=on, action_id=r.action_id, amount_minor=r.amount_minor,
                      currency=r.currency, status=r.status, created_at=r.created_at) for r, on in rows]


@router.get("/messages", response_model=list[MessageOut])
def messages(principal: Principal = Depends(require_operator), db: Session = Depends(get_db),
             limit: int = Query(default=100, ge=1, le=500)):
    rows = db.execute(
        select(OutboundMessage, Ticket.ticket_number).join(Ticket, Ticket.id == OutboundMessage.ticket_id)
        .where(OutboundMessage.tenant_id == principal.tenant_id)
        .order_by(OutboundMessage.created_at.desc()).limit(limit)
    ).all()
    return [MessageOut(message_id=m.id, ticket_number=tn, action_id=m.action_id, destination=m.destination,
                       body=m.body, status=m.status, created_at=m.created_at) for m, tn in rows]


@router.get("/audit-events", response_model=list[AuditEventOut])
def audit_events(
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
    event_type: str | None = None,
    run_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
):
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if run_id:
        stmt = stmt.where(AuditEvent.run_id == run_id)
    rows = db.scalars(stmt.order_by(AuditEvent.created_at.desc()).limit(limit))
    return [AuditEventOut(id=e.id, actor_type=e.actor_type, actor_id=e.actor_id, run_id=e.run_id,
                          action_id=e.action_id, event_type=e.event_type, metadata=e.metadata_,
                          created_at=e.created_at) for e in rows]
