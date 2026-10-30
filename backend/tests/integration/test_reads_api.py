from tests.conftest import ADMIN, GLOBEX_SUPERVISOR, OPERATOR, SUPERVISOR


def test_seeded_t101_and_o101_are_accessible(client):
    r = client.get("/api/v1/tickets/T-101", headers=OPERATOR())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order_number"] == "O-101"
    assert body["order"]["total_amount_minor"] == 120000
    assert body["order"]["shipping_status"] == "delayed"
    assert body["order"]["refunded"] is False

    order = client.get("/api/v1/orders/O-101", headers=OPERATOR()).json()
    assert [e["event_type"] for e in order["delivery_events"]][:2] == ["order_placed", "shipped"]


def test_ticket_list_filters_and_pages(client):
    r = client.get("/api/v1/tickets", params={"priority": "high", "status": "open", "limit": 2},
                   headers=OPERATOR())
    page = r.json()
    assert [t["ticket_number"] for t in page["items"]] == ["T-101", "T-102"]
    assert page["next_cursor"] == "T-102"
    nxt = client.get("/api/v1/tickets", params={"priority": "high", "status": "open", "limit": 2,
                                                "cursor": page["next_cursor"]}, headers=OPERATOR()).json()
    assert nxt["items"][0]["ticket_number"] == "T-105"


def test_active_policy(client):
    body = client.get("/api/v1/policies/active", headers=OPERATOR()).json()
    assert body["version"] == "2026-01" and body["min_delay_days"] == 5 and body["refund_percent"] == 100


def test_missing_token_is_401_with_stable_error_shape(client):
    r = client.get("/api/v1/tickets")
    assert r.status_code == 401
    body = r.json()
    assert body["error_code"] == "unauthenticated" and body["request_id"]


def test_t26_cross_tenant_ticket_fetch_is_denied(client):
    assert client.get("/api/v1/tickets/T-201", headers=OPERATOR()).status_code == 404
    assert client.get("/api/v1/tickets/T-101", headers=GLOBEX_SUPERVISOR()).status_code == 404
    globex = client.get("/api/v1/tickets", headers=GLOBEX_SUPERVISOR()).json()
    assert [t["ticket_number"] for t in globex["items"]] == ["T-201"]


def test_audit_requires_admin(client):
    assert client.get("/api/v1/audit-events", headers=SUPERVISOR()).status_code == 403
    assert client.get("/api/v1/audit-events", headers=ADMIN()).status_code == 200


def test_health(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"] == {"database": "ok", "checkpointer": "ok"}


def test_unknown_ticket_returns_clear_not_found(client):
    r = client.post("/api/v1/runs", json={"mode": "ticket", "ticket_number": "T-999", "instruction": "check"},
                    headers=OPERATOR())
    assert r.status_code == 404
    assert r.json()["error_code"] == "not_found"


def test_ticket_list_includes_order_state_for_the_queue_view(client):
    items = {t["ticket_number"]: t for t in client.get("/api/v1/tickets", headers=OPERATOR()).json()["items"]}
    assert items["T-101"]["order_shipping_status"] == "delayed"
    assert items["T-101"]["days_past_promised_delivery"] == 8.0
    assert items["T-101"]["order_refunded"] is False
    assert items["T-106"]["order_refunded"] is True
    assert items["T-104"]["days_past_promised_delivery"] is None  # delivered
    assert items["T-110"]["order_number"] is None
