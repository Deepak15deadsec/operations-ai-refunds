"""PolicyService is pure and deterministic: no DB, no LLM."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Order, RefundPolicy
from app.services.policy import PolicyService

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def order(**kw) -> Order:
    base = dict(order_number="O-1", total_amount_minor=120000, currency="INR", payment_status="paid",
                shipping_status="delayed", promised_delivery_at=NOW - timedelta(days=7), actual_delivery_at=None)
    base.update(kw)
    return Order(**base)


def policy(**kw) -> RefundPolicy:
    base = dict(version="2026-01", min_delay_days=5, refund_percent=100, active=True, policy_text="")
    base.update(kw)
    return RefundPolicy(**base)


def evaluate(o=None, p=None, now=NOW, refunded=False):
    return PolicyService.evaluate_refund(o or order(), p or policy(), now, already_refunded=refunded)


def test_t01_delayed_paid_order_is_eligible_for_full_amount():
    result = evaluate()
    assert result.eligible
    assert result.max_amount_minor == 120000
    assert result.policy_version == "2026-01"


def test_t06_four_day_delay_is_not_eligible():
    result = evaluate(order(promised_delivery_at=NOW - timedelta(days=4)))
    assert not result.eligible
    assert result.max_amount_minor == 0
    assert any("threshold" in r for r in result.reasons)


def test_threshold_uses_exact_elapsed_duration():
    exactly = order(promised_delivery_at=NOW - timedelta(days=5))
    just_short = order(promised_delivery_at=NOW - timedelta(days=5) + timedelta(seconds=1))
    assert evaluate(exactly).eligible
    assert not evaluate(just_short).eligible


def test_t07_delivered_order_is_ineligible():
    assert not evaluate(order(shipping_status="delivered", actual_delivery_at=NOW - timedelta(days=1))).eligible


def test_delayed_status_with_actual_delivery_is_ineligible():
    assert not evaluate(order(actual_delivery_at=NOW - timedelta(days=1))).eligible


@pytest.mark.parametrize("payment", ["failed", "pending"])
def test_t08_unpaid_order_is_ineligible(payment):
    assert not evaluate(order(payment_status=payment)).eligible


def test_t09_already_refunded_is_ineligible():
    result = evaluate(refunded=True)
    assert not result.eligible
    assert "already been refunded" in " ".join(result.reasons)


def test_policy_min_delay_days_is_respected():
    assert not evaluate(p=policy(min_delay_days=10)).eligible
    assert evaluate(order(promised_delivery_at=NOW - timedelta(days=2)), policy(min_delay_days=1)).eligible


def test_t36_partial_refund_percent_uses_floor_in_minor_units():
    result = evaluate(order(total_amount_minor=99999), policy(refund_percent=50))
    assert result.eligible
    assert result.max_amount_minor == 49999


def test_zero_percent_policy_permits_no_refund():
    assert not evaluate(p=policy(refund_percent=0)).eligible


def test_inactive_policy_is_not_applied():
    assert not evaluate(p=policy(active=False)).eligible
