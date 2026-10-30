"""Structured output the investigation agent must return. Bounded sizes everywhere."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

TicketNumber = Annotated[str, Field(pattern=r"^T-\d{1,8}$", max_length=12)]
OrderNumber = Annotated[str, Field(pattern=r"^O-\d{1,8}$", max_length=12)]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(max_length=500)
    source_type: Literal["ticket", "order", "delivery_event", "policy", "customer"]
    source_id: str = Field(max_length=64)


class RefundProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["refund"]
    order_number: OrderNumber
    amount_minor: int = Field(gt=0, le=10**12, description="Amount in minor units (paise)")
    currency: Literal["INR"]
    reason: str = Field(max_length=500)


class SendReplyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["send_reply"]
    ticket_number: TicketNumber
    message_body: str = Field(min_length=1, max_length=2000)
    reason: str = Field(max_length=500)


class EscalateTicketProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["escalate_ticket"]
    ticket_number: TicketNumber
    reason: str = Field(max_length=500)


class NoActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["no_action"]
    ticket_number: TicketNumber
    reason: str = Field(max_length=500)


Proposal = Annotated[
    RefundProposal | SendReplyProposal | EscalateTicketProposal | NoActionProposal,
    Field(discriminator="action_type"),
]


class InvestigationResult(BaseModel):
    """Findings and proposed actions for one support ticket."""

    model_config = ConfigDict(extra="forbid")
    ticket_number: TicketNumber
    summary: str = Field(max_length=2000)
    findings: list[Finding] = Field(default_factory=list, max_length=20)
    proposals: list[Proposal] = Field(default_factory=list, max_length=5)
    requires_human_followup: bool = False
