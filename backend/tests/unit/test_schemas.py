import pytest
from pydantic import ValidationError

from app.schemas.investigation import InvestigationResult, RefundProposal, SendReplyProposal
from app.services.hashing import action_fingerprint


def test_discriminated_union_parses_each_action_type():
    result = InvestigationResult.model_validate({
        "ticket_number": "T-101", "summary": "s",
        "proposals": [
            {"action_type": "refund", "order_number": "O-101", "amount_minor": 120000, "currency": "INR",
             "reason": "r"},
            {"action_type": "send_reply", "ticket_number": "T-101", "message_body": "hi", "reason": "r"},
            {"action_type": "escalate_ticket", "ticket_number": "T-101", "reason": "r"},
            {"action_type": "no_action", "ticket_number": "T-101", "reason": "r"},
        ],
    })
    assert isinstance(result.proposals[0], RefundProposal)
    assert isinstance(result.proposals[1], SendReplyProposal)
    assert [p.action_type for p in result.proposals] == ["refund", "send_reply", "escalate_ticket", "no_action"]


@pytest.mark.parametrize("bad", [
    {"action_type": "refund", "order_number": "O-101", "amount_minor": -5, "currency": "INR", "reason": "r"},
    {"action_type": "refund", "order_number": "O-101", "amount_minor": 1.5, "currency": "INR", "reason": "r"},
    {"action_type": "refund", "order_number": "O-101", "amount_minor": 100, "currency": "USD", "reason": "r"},
    {"action_type": "issue_refund_now", "order_number": "O-101"},
    {"action_type": "send_reply", "ticket_number": "T-101", "message_body": "x" * 2001, "reason": "r"},
    {"action_type": "refund", "order_number": "DROP TABLE", "amount_minor": 1, "currency": "INR", "reason": "r"},
])
def test_invalid_proposals_are_rejected(bad):
    with pytest.raises(ValidationError):
        InvestigationResult.model_validate({"ticket_number": "T-101", "summary": "s", "proposals": [bad]})


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        InvestigationResult.model_validate({"ticket_number": "T-101", "summary": "s", "tenant_id": "x"})


def test_proposal_count_is_bounded():
    many = [{"action_type": "no_action", "ticket_number": "T-1", "reason": "r"}] * 6
    with pytest.raises(ValidationError):
        InvestigationResult.model_validate({"ticket_number": "T-1", "summary": "s", "proposals": many})


def test_fingerprint_is_order_independent_and_sensitive_to_values():
    import uuid

    tid = uuid.uuid4()
    a = action_fingerprint(action_type="refund", ticket_id=tid, payload={"a": 1, "b": 2}, policy_version="v")
    b = action_fingerprint(action_type="refund", ticket_id=tid, payload={"b": 2, "a": 1}, policy_version="v")
    c = action_fingerprint(action_type="refund", ticket_id=tid, payload={"a": 1, "b": 3}, policy_version="v")
    assert a == b != c
