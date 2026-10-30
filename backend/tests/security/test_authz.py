"""Authorization, tenant isolation, tamper resistance and database-level guarantees."""

import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.seed import ACME, GLOBEX
from app.db.session import allow_maintenance, transaction
from tests.conftest import (
    GLOBEX_SUPERVISOR,
    OPERATOR,
    SUPERVISOR,
    bearer,
    count,
    drain,
    investigation_script,
    make_token,
    refund,
    use_script,
)
from tests.integration.test_workflow import approvals_for, decide, refunds, start


@pytest.fixture
def pending_refund(client, graph):
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    return run_id, approvals_for(client, run_id)["refund"]


def test_t14_operator_cannot_approve(client, graph, pending_refund):
    _, card = pending_refund
    r = decide(client, card["approval_id"], "approve", headers=OPERATOR())
    assert r.status_code == 403 and r.json()["error_code"] == "forbidden"
    assert client.get("/api/v1/approvals", headers=OPERATOR()).status_code == 403
    drain(graph)
    assert refunds() == 0


def test_t15_other_tenant_supervisor_cannot_see_or_decide(client, graph, pending_refund):
    _, card = pending_refund
    assert client.get(f"/api/v1/approvals/{card['approval_id']}", headers=GLOBEX_SUPERVISOR()).status_code == 404
    r = decide(client, card["approval_id"], "approve", headers=GLOBEX_SUPERVISOR())
    assert r.status_code == 404
    assert client.get("/api/v1/approvals", headers=GLOBEX_SUPERVISOR()).json() == []
    drain(graph)
    assert refunds() == 0


def test_t27_cross_tenant_run_and_event_enumeration_denied(client, pending_refund):
    run_id, _ = pending_refund
    other = GLOBEX_SUPERVISOR()
    assert client.get(f"/api/v1/runs/{run_id}", headers=other).status_code == 404
    assert client.get(f"/api/v1/runs/{run_id}/events", headers=other).status_code == 404
    assert client.post(f"/api/v1/runs/{run_id}/cancel", headers=other).status_code == 404
    assert client.get("/api/v1/runs", headers=other).json() == []
    assert client.get(f"/api/v1/runs/{uuid.uuid4()}", headers=OPERATOR()).status_code == 404


def test_malicious_approval_payload_is_rejected(client, graph, pending_refund):
    _, card = pending_refund
    r = client.post(f"/api/v1/approvals/{card['approval_id']}/decision",
                    json={"decision": "approve", "amount_minor": 99999999, "tenant_id": str(GLOBEX),
                          "action_hash": "0" * 64}, headers=SUPERVISOR())
    assert r.status_code == 422 and r.json()["error_code"] == "validation_error"
    assert client.post(f"/api/v1/approvals/{uuid.uuid4()}/decision", json={"decision": "approve"},
                       headers=SUPERVISOR()).status_code == 404  # forged id
    drain(graph)
    assert refunds() == 0


def test_tenant_id_in_run_request_body_is_refused(client):
    r = client.post("/api/v1/runs", json={"mode": "ticket", "ticket_number": "T-201", "instruction": "x",
                                          "tenant_id": str(GLOBEX)}, headers=OPERATOR())
    assert r.status_code == 422


def test_t17_proposal_modified_after_submission_is_never_executed(client, graph, pending_refund):
    run_id, card = pending_refund
    # The immutability trigger blocks ordinary updates...
    with pytest.raises(DBAPIError), transaction() as session:
        session.execute(text("UPDATE proposed_actions SET payload = jsonb_set(payload, '{amount_minor}', "
                             "'999999') WHERE id = :id"), {"id": card["action_id"]})
    # ...and even a privileged tamper (trigger bypassed) is caught by the hash check.
    with transaction() as session:
        allow_maintenance(session)
        session.execute(text("UPDATE proposed_actions SET payload = jsonb_set(payload, '{amount_minor}', "
                             "'999999') WHERE id = :id"), {"id": card["action_id"]})
    r = decide(client, card["approval_id"], "approve")
    assert r.status_code == 409 and r.json()["error_code"] == "action_hash_mismatch"
    drain(graph)
    assert refunds() == 0


def test_t17b_tamper_after_approval_is_caught_by_executor(client, graph, pending_refund):
    _, card = pending_refund
    assert decide(client, card["approval_id"], "approve").status_code == 200
    with transaction() as session:
        allow_maintenance(session)
        session.execute(text("UPDATE proposed_actions SET payload = jsonb_set(payload, '{amount_minor}', "
                             "'999999') WHERE id = :id"), {"id": card["action_id"]})
    drain(graph)
    assert refunds() == 0
    assert count("SELECT count(*) FROM proposed_actions WHERE status_reason='action_hash_mismatch'") == 1


def test_t33_audit_events_are_append_only(client, pending_refund):
    assert count("SELECT count(*) FROM audit_events") > 0
    for sql in ("UPDATE audit_events SET event_type = 'x'", "DELETE FROM audit_events",
                "TRUNCATE audit_events CASCADE"):
        with pytest.raises(DBAPIError, match="append-only"), transaction() as session:
            session.execute(text(sql))


@pytest.mark.parametrize("token_kwargs, status", [
    ({"tenant_id": None}, 403),
    ({"tenant_id": "not-a-uuid"}, 403),
    ({"audience": "account"}, 401),
    ({"issuer": "http://evil/realms/operations-demo"}, 401),
    ({"expires_in": -60}, 401),
    ({"key": rsa.generate_private_key(public_exponent=65537, key_size=2048)}, 401),
])
def test_t34_invalid_tokens_are_rejected(client, token_kwargs, status):
    token = make_token(["supervisor"], **{"tenant_id": ACME, **token_kwargs})
    r = client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == status, r.text


def test_token_without_application_role_is_forbidden(client):
    assert client.get("/api/v1/tickets", headers=bearer("offline_access")).status_code == 403


def test_unsigned_alg_none_token_is_rejected(client):
    import jwt

    token = jwt.encode({"sub": "x", "tenant_id": str(ACME), "realm_access": {"roles": ["admin"]}}, key=None,
                       algorithm="none")
    assert client.get("/api/v1/tickets", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_t30_batch_over_limit_is_rejected_explicitly(client):
    r = client.post("/api/v1/runs", json={"mode": "batch", "instruction": "x", "limit": 11}, headers=OPERATOR())
    assert r.status_code == 400 and r.json()["error_code"] == "batch_limit_exceeded"


def test_secrets_are_redacted_from_events_and_audit(client, graph):
    from app.services import audit

    with transaction() as session:
        audit.record(session, tenant_id=ACME, actor_type="system", actor_id="t", event_type="x",
                     metadata={"access_token": "abc", "nested": {"api_key": "k"}})
    assert count("SELECT count(*) FROM audit_events WHERE metadata::text LIKE '%abc%'") == 0
    assert count("SELECT count(*) FROM audit_events WHERE metadata::text LIKE '%[redacted]%'") == 1
