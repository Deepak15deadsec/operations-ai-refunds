"""SQLAlchemy ORM models. The Alembic migration is the source of truth for constraints/triggers."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    order_number: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    total_amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    payment_status: Mapped[str] = mapped_column(String(16))
    shipping_status: Mapped[str] = mapped_column(String(16))
    promised_delivery_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    ticket_number: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    subject: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class RefundPolicy(Base):
    __tablename__ = "refund_policies"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    version: Mapped[str] = mapped_column(String(32))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    min_delay_days: Mapped[int] = mapped_column(Integer, default=5)
    refund_percent: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(default=False)
    policy_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    requested_by_user_id: Mapped[str] = mapped_column(String(255))
    requested_by_name: Mapped[str | None] = mapped_column(String(255))
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id"))
    mode: Mapped[str] = mapped_column(String(16), default="ticket")
    original_instruction: Mapped[str] = mapped_column(Text)
    batch_filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    thread_id: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AgentEvent(Base):
    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _tenant()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class ProposedAction(Base):
    __tablename__ = "proposed_actions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"))
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"))
    action_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="proposed")
    status_reason: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposed_actions.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requested_by: Mapped[str] = mapped_column(String(255))
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_by_name: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proposed_actions.id"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default="simulated_success")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"))
    action_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("proposed_actions.id"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    destination: Mapped[str] = mapped_column(String(320))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="simulated_sent")
    created_at: Mapped[datetime] = _created()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(255))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    action_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proposed_actions.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class WorkerJob(Base):
    __tablename__ = "worker_jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    job_type: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
