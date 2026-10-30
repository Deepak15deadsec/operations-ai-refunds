"""Deterministic refund eligibility. The LLM's opinion is never the source of truth."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.db.models import Order, RefundPolicy


@dataclass(frozen=True)
class RefundEvaluation:
    eligible: bool
    max_amount_minor: int
    currency: str
    policy_version: str
    evaluated_at: datetime
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "max_amount_minor": self.max_amount_minor,
            "currency": self.currency,
            "policy_version": self.policy_version,
            "evaluated_at": self.evaluated_at.isoformat(),
            "reasons": self.reasons,
        }


class PolicyService:
    @staticmethod
    def refundable_amount(order: Order, policy: RefundPolicy) -> int:
        return order.total_amount_minor * policy.refund_percent // 100

    @staticmethod
    def evaluate_refund(
        order: Order, policy: RefundPolicy, now_utc: datetime, *, already_refunded: bool
    ) -> RefundEvaluation:
        """Rules 2-6 of the spec. Rule 1 (tenant + ticket linkage), rule 7 (requested amount) and
        rule 8 (approval) are checked by the proposal validator and executor around this call."""
        reasons: list[str] = []
        if order.payment_status != "paid":
            reasons.append(f"payment_status is {order.payment_status}, not paid")
        if order.shipping_status != "delayed" or order.actual_delivery_at is not None:
            reasons.append(f"shipping_status is {order.shipping_status}, not an undelivered delay")
        threshold = order.promised_delivery_at + timedelta(days=policy.min_delay_days)
        if now_utc < threshold:
            reasons.append(
                f"delay threshold not reached: eligible from {threshold.isoformat()} "
                f"({policy.min_delay_days} days after promised delivery)"
            )
        if already_refunded:
            reasons.append("order has already been refunded")
        if not policy.active:
            reasons.append(f"policy {policy.version} is not active")
        if policy.refund_percent <= 0:
            reasons.append("policy does not permit refunds")
        amount = PolicyService.refundable_amount(order, policy)
        if amount <= 0:
            reasons.append("refundable amount is zero")
        eligible = not reasons
        return RefundEvaluation(
            eligible=eligible,
            max_amount_minor=amount if eligible else 0,
            currency=order.currency,
            policy_version=policy.version,
            evaluated_at=now_utc,
            reasons=reasons or ["all refund conditions met"],
        )
