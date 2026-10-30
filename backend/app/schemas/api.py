"""API request and response models."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class TicketOut(BaseModel):
    ticket_number: str
    subject: str
    description: str
    priority: str
    status: str
    customer_name: str
    order_number: str | None
    created_at: datetime
    order_payment_status: str | None = None
    order_shipping_status: str | None = None
    order_total_minor: int | None = None
    days_past_promised_delivery: float | None = None
    order_refunded: bool | None = None


class DeliveryEventOut(ORM):
    event_type: str
    event_time: datetime
    description: str


class OrderOut(BaseModel):
    order_number: str
    total_amount_minor: int
    currency: str
    payment_status: str
    shipping_status: str
    promised_delivery_at: datetime
    actual_delivery_at: datetime | None
    customer_name: str
    refunded: bool


class OrderDetailOut(OrderOut):
    delivery_events: list[DeliveryEventOut]


class TicketDetailOut(TicketOut):
    order: OrderOut | None


class PolicyOut(ORM):
    version: str
    effective_from: datetime
    min_delay_days: int
    refund_percent: int
    policy_text: str


class StartRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["ticket", "batch"] = "ticket"
    ticket_number: str | None = Field(default=None, pattern=r"^T-\d{1,8}$")
    instruction: str = Field(min_length=1, max_length=2000)
    filters: dict[str, str] | None = None
    limit: int | None = Field(default=None, ge=1)


class StartRunResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    events_url: str


class ApprovalSummary(BaseModel):
    approval_id: uuid.UUID
    action_id: uuid.UUID
    action_type: str
    status: str
    action_status: str


class ActionOut(BaseModel):
    action_id: uuid.UUID
    action_type: str
    payload: dict[str, Any]
    status: str
    status_reason: str | None
    reason: str
    evidence: list[Any]
    policy_version: str | None
    approval: ApprovalSummary | None


class RunOut(BaseModel):
    run_id: uuid.UUID
    mode: str
    status: str
    ticket_number: str | None
    parent_run_id: uuid.UUID | None
    original_instruction: str
    requested_by_user_id: str
    requested_by_name: str | None = None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunDetailOut(RunOut):
    findings: dict[str, Any] | None
    summary: dict[str, Any] | None
    usage: dict[str, Any] | None
    actions: list[ActionOut]
    children: list[RunOut]


class ApprovalOut(BaseModel):
    approval_id: uuid.UUID
    action_id: uuid.UUID
    run_id: uuid.UUID
    ticket_number: str
    ticket_subject: str = ""
    order_number: str | None
    action_type: str
    payload: dict[str, Any]
    reason: str
    evidence: list[Any]
    policy_version: str | None
    status: str
    action_status: str
    action_status_reason: str | None
    action_hash: str
    requested_by: str
    requested_by_name: str | None = None
    decided_by: str | None
    decided_by_name: str | None = None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
    expires_at: datetime
    permitted_reviewer_roles: list[str] = ["supervisor", "admin"]
    simulated: bool = True


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=1000)


class RefundOut(BaseModel):
    refund_id: uuid.UUID
    order_number: str
    action_id: uuid.UUID | None
    amount_minor: int
    currency: str
    status: str
    created_at: datetime


class MessageOut(BaseModel):
    message_id: uuid.UUID
    ticket_number: str
    action_id: uuid.UUID
    destination: str
    body: str
    status: str
    created_at: datetime


class AuditEventOut(BaseModel):
    id: uuid.UUID
    actor_type: str
    actor_id: str
    run_id: uuid.UUID | None
    action_id: uuid.UUID | None
    event_type: str
    metadata: dict[str, Any]
    created_at: datetime


class OverviewOut(BaseModel):
    open_tickets: int
    high_priority_open_tickets: int
    pending_approvals: int
    runs_today: int
    simulated_refunds: int
    simulated_refund_total_minor: int


class MeOut(BaseModel):
    user_id: str
    username: str | None
    tenant_id: uuid.UUID
    roles: list[str]
