"""End-to-end workflow through the real API, graph, checkpointer and executor (scripted LLM)."""

from datetime import timedelta

from langchain_core.messages import AIMessage

from app.agent.models import tool_call
from app.core.clock import set_clock
from app.workflow.checkpoint import make_checkpointer, open_pool
from app.workflow.graph import build_graph
from tests.conftest import (
    NOW,
    OPERATOR,
    SUPERVISOR,
    count,
    drain,
    investigation_script,
    refund,
    reply,
    use_script,
)


def start(client, ticket: str, instruction: str = "Investigate and prepare a resolution.") -> str:
    r = client.post("/api/v1/runs", json={"mode": "ticket", "ticket_number": ticket, "instruction": instruction},
                    headers=OPERATOR())
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued"
    return r.json()["run_id"]


def run_detail(client, run_id: str) -> dict:
    r = client.get(f"/api/v1/runs/{run_id}", headers=OPERATOR())
    assert r.status_code == 200, r.text
    return r.json()


def approvals_for(client, run_id: str) -> dict[str, dict]:
    rows = client.get("/api/v1/approvals", params={"run_id": run_id}, headers=SUPERVISOR()).json()
    return {a["action_type"]: a for a in rows}


def decide(client, approval_id: str, decision: str, headers=None):
    return client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": decision, "note": "ok"},
                       headers=headers or SUPERVISOR())


def refunds() -> int:
    return count("SELECT count(*) FROM refunds WHERE action_id IS NOT NULL")


def messages() -> int:
    return count("SELECT count(*) FROM outbound_messages")


def test_t01_t02_refund_waits_for_approval_then_executes_exactly_once(client, graph):
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000), reply("T-101")]))
    run_id = start(client, "T-101")
    drain(graph)

    detail = run_detail(client, run_id)
    assert detail["status"] == "awaiting_approval"
    assert {a["action_type"]: a["status"] for a in detail["actions"]} == {
        "refund": "pending_approval", "send_reply": "pending_approval"}
    assert refunds() == 0 and messages() == 0  # T01: nothing before approval

    pending = approvals_for(client, run_id)
    card = pending["refund"]
    assert card["payload"] == {"order_number": "O-101", "amount_minor": 120000, "currency": "INR"}
    assert card["policy_version"] == "2026-01" and card["simulated"] is True
    assert any(e.get("source_type") == "policy_evaluation" and e["eligible"] for e in card["evidence"])

    assert decide(client, card["approval_id"], "approve").status_code == 200
    drain(graph)
    assert refunds() == 1
    assert count("SELECT amount_minor FROM refunds WHERE action_id IS NOT NULL") == 120000
    assert run_detail(client, run_id)["status"] == "awaiting_approval"  # reply still pending

    # T04 / T32: repeating the approval and re-running jobs creates nothing new
    again = decide(client, card["approval_id"], "approve")
    assert again.status_code == 200 and again.json()["status"] == "approved"
    assert count("SELECT count(*) FROM worker_jobs WHERE job_type='resume'") == 1
    drain(graph)
    assert refunds() == 1

    assert decide(client, pending["send_reply"]["approval_id"], "approve").status_code == 200
    drain(graph)
    assert messages() == 1
    final = run_detail(client, run_id)
    assert final["status"] == "completed"
    assert {a["status"] for a in final["actions"]} == {"completed"}
    assert count("SELECT count(*) FROM audit_events WHERE event_type='refund_executed'") == 1


def test_t03_t24_rejection_creates_no_side_effects(client, graph):
    use_script(investigation_script("T-102", "O-102", [refund("O-102", 249900), reply("T-102")]))
    run_id = start(client, "T-102")
    drain(graph)
    pending = approvals_for(client, run_id)
    assert decide(client, pending["refund"]["approval_id"], "reject").status_code == 200
    assert decide(client, pending["send_reply"]["approval_id"], "reject").status_code == 200
    drain(graph)
    assert refunds() == 0 and messages() == 0
    detail = run_detail(client, run_id)
    assert detail["status"] == "rejected"
    # a rejected approval cannot be flipped to approved afterwards
    flip = decide(client, pending["refund"]["approval_id"], "approve")
    assert flip.status_code == 409 and flip.json()["error_code"] == "approval_already_decided"


def test_t23_t31_reply_and_refund_approved_at_different_times(client, graph):
    use_script(investigation_script("T-108", "O-108", [refund("O-108", 45000), reply("T-108")]))
    run_id = start(client, "T-108")
    drain(graph)
    pending = approvals_for(client, run_id)
    decide(client, pending["send_reply"]["approval_id"], "approve")
    drain(graph)
    assert messages() == 1 and refunds() == 0
    assert run_detail(client, run_id)["status"] == "awaiting_approval"
    decide(client, pending["refund"]["approval_id"], "reject")
    drain(graph)
    assert messages() == 1 and refunds() == 0
    assert run_detail(client, run_id)["status"] == "completed"


def test_t19_worker_restart_while_awaiting_approval(client, checkpoint_pool):
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    first_graph = build_graph(make_checkpointer(checkpoint_pool))
    drain(first_graph)
    assert run_detail(client, run_id)["status"] == "awaiting_approval"

    # "Restart": a brand-new pool + graph instance with no in-memory state.
    approval_id = approvals_for(client, run_id)["refund"]["approval_id"]
    decide(client, approval_id, "approve")
    fresh_pool = open_pool(max_size=2)
    try:
        drain(build_graph(make_checkpointer(fresh_pool)))
    finally:
        fresh_pool.close()
    assert refunds() == 1
    assert run_detail(client, run_id)["status"] == "completed"


def test_t20_crash_after_commit_retry_recognises_existing_effect(client, graph):
    from app.db.session import transaction
    from app.services.executor import execute_action

    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    card = approvals_for(client, run_id)["refund"]
    decide(client, card["approval_id"], "approve")
    # Simulate: executor committed, then the worker died before the graph checkpointed/acked.
    with transaction() as session:
        first = execute_action(session, card["action_id"])
    assert first.status == "completed" and not first.already_done
    drain(graph)  # the resume job runs the execute node again
    with transaction() as session:
        again = execute_action(session, card["action_id"])
    assert again.already_done and again.effect_id == first.effect_id
    assert refunds() == 1
    assert run_detail(client, run_id)["status"] == "completed"


def test_t05_same_order_proposed_in_a_different_run(client, graph):
    for _ in range(2):
        use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
        start(client, "T-101")
    drain(graph)
    rows = client.get("/api/v1/approvals", params={"status": "pending"}, headers=SUPERVISOR()).json()
    assert len(rows) == 2
    for row in rows:
        decide(client, row["approval_id"], "approve")
    drain(graph)
    assert refunds() == 1
    reasons = count("SELECT count(*) FROM proposed_actions WHERE status_reason = 'already_refunded'")
    assert reasons == 1


def test_t12_hallucinated_amount_is_rejected_by_policy(client, graph):
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 1000000)]))
    run_id = start(client, "T-101")
    drain(graph)
    detail = run_detail(client, run_id)
    action = detail["actions"][0]
    assert action["status"] == "failed" and action["status_reason"] == "amount_mismatch"
    assert action["approval"] is None
    assert detail["status"] == "completed_no_action"
    assert refunds() == 0


def test_t06_t07_t08_t09_ineligible_refund_proposals_are_not_executable(client, graph):
    cases = {"T-103": ("O-103", 75000), "T-104": ("O-104", 159900), "T-105": ("O-105", 99900),
             "T-106": ("O-106", 54900)}
    run_ids = {}
    for ticket, (order, amount) in cases.items():
        use_script(investigation_script(ticket, order, [refund(order, amount)]))
        run_ids[ticket] = start(client, ticket)
        drain(graph)
    for ticket, run_id in run_ids.items():
        action = run_detail(client, run_id)["actions"][0]
        assert action["status"] == "failed", ticket
        assert action["status_reason"] == "policy_ineligible", ticket
        assert action["approval"] is None
    assert count("SELECT count(*) FROM approval_requests") == 0
    assert refunds() == 0


def test_t11_refund_for_order_not_linked_to_ticket(client, graph):
    use_script(investigation_script("T-109", "O-109", [refund("O-101", 120000)]))
    run_id = start(client, "T-109")
    drain(graph)
    action = run_detail(client, run_id)["actions"][0]
    assert action["status_reason"] == "order_not_linked_to_ticket"
    assert refunds() == 0


def test_t18_order_change_after_approval_blocks_stale_refund(client, graph):
    from sqlalchemy import text

    from app.db.session import transaction

    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    card = approvals_for(client, run_id)["refund"]
    with transaction() as session:  # delivered after the proposal was made
        session.execute(text("UPDATE orders SET shipping_status='delivered', actual_delivery_at=now() "
                             "WHERE order_number='O-101'"))
    decide(client, card["approval_id"], "approve")
    drain(graph)
    action = run_detail(client, run_id)["actions"][0]
    assert action["status"] == "failed" and action["status_reason"] == "no_longer_eligible"
    assert run_detail(client, run_id)["status"] == "failed"
    assert refunds() == 0


def test_policy_change_after_proposal_needs_review(client, graph):
    from sqlalchemy import text

    from app.db.session import transaction

    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    card = approvals_for(client, run_id)["refund"]
    with transaction() as session:
        session.execute(text("UPDATE refund_policies SET active = false WHERE version = '2026-01'"))
        session.execute(text("UPDATE refund_policies SET active = true WHERE version = '2025-07'"))
    decide(client, card["approval_id"], "approve")
    drain(graph)
    action = run_detail(client, run_id)["actions"][0]
    assert action["status"] == "needs_review" and action["status_reason"] == "policy_changed"
    assert run_detail(client, run_id)["status"] == "needs_human_review"
    assert refunds() == 0


def test_t16_expired_approval_is_never_executed(client, graph):
    from app.db.session import transaction
    from app.services.approvals import expire_due

    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    card = approvals_for(client, run_id)["refund"]
    set_clock(lambda: NOW + timedelta(hours=24, seconds=1))
    late = decide(client, card["approval_id"], "approve")
    assert late.status_code == 409 and late.json()["error_code"] == "approval_expired"
    with transaction() as session:
        expire_due(session)
    drain(graph)
    assert refunds() == 0
    detail = run_detail(client, run_id)
    assert detail["actions"][0]["status"] == "expired"
    assert detail["status"] == "rejected"


def test_sweeper_expires_pending_approvals_and_finishes_run(client, graph):
    from app.db.session import transaction
    from app.services.approvals import expire_due

    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    set_clock(lambda: NOW + timedelta(hours=25))
    with transaction() as session:
        assert expire_due(session) == 1
    drain(graph)
    assert run_detail(client, run_id)["status"] == "rejected"
    assert count("SELECT count(*) FROM audit_events WHERE event_type='approval_expired'") == 1


def test_t22_malformed_structured_output_retries_once_then_needs_review(client, graph):
    bad = {"ticket_number": "T-101", "summary": "x",
           "proposals": [{"action_type": "refund", "order_number": "O-101", "amount_minor": "lots"}]}
    use_script([
        AIMessage(content="", tool_calls=[tool_call("get_ticket", {"ticket_number": "T-101"})]),
        AIMessage(content="", tool_calls=[tool_call("InvestigationResult", bad)]),
        AIMessage(content="", tool_calls=[tool_call("InvestigationResult", bad)]),
        AIMessage(content="", tool_calls=[tool_call("InvestigationResult", bad)]),
    ])
    run_id = start(client, "T-101")
    drain(graph)
    detail = run_detail(client, run_id)
    assert detail["status"] == "needs_human_review"
    assert detail["error_code"] in ("invalid_structured_output", "no_structured_output")
    assert detail["actions"] == []
    events = count(
        "SELECT count(*) FROM agent_events WHERE run_id = :r AND event_type='structured_output_retry'", r=run_id)
    assert events == 1


def test_structured_output_recovers_after_one_retry(client, graph):
    bad = {"ticket_number": "T-101", "summary": "x", "proposals": [{"action_type": "refund"}]}
    good = investigation_script("T-101", "O-101", [refund("O-101", 120000)])
    use_script([good[0], good[1], AIMessage(content="", tool_calls=[tool_call("InvestigationResult", bad)]),
                good[2]])
    run_id = start(client, "T-101")
    drain(graph)
    assert run_detail(client, run_id)["status"] == "awaiting_approval"


def test_llm_not_configured_fails_clearly(client, graph):
    from app.agent.models import AgentConfigError
    from tests.conftest import use_model

    def missing(_name):
        raise AgentConfigError("AGENT_MODEL uses openai but OPENAI_API_KEY is not set")

    use_model(missing)
    run_id = start(client, "T-101")
    drain(graph)
    detail = run_detail(client, run_id)
    assert detail["status"] == "failed" and detail["error_code"] == "llm_not_configured"
    assert "OPENAI_API_KEY" in detail["error_message"]


def test_cancel_pending_run_expires_approvals(client, graph):
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    r = client.post(f"/api/v1/runs/{run_id}/cancel", headers=OPERATOR())
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    card = approvals_for(client, run_id)["refund"]
    assert card["status"] == "expired"
    assert decide(client, card["approval_id"], "approve").status_code == 409
    drain(graph)
    assert refunds() == 0


def test_no_action_proposal_completes_without_approvals(client, graph):
    use_script(investigation_script("T-110", None, [
        {"action_type": "no_action", "ticket_number": "T-110", "reason": "General question"}]))
    run_id = start(client, "T-110")
    drain(graph)
    detail = run_detail(client, run_id)
    assert detail["status"] == "completed_no_action"
    assert detail["summary"]["no_action_reasons"] == ["General question"]


def test_display_names_are_recorded_for_requester_and_decider(client, graph):
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    assert run_detail(client, run_id)["requested_by_name"] == "olivia"
    card = approvals_for(client, run_id)["refund"]
    assert card["requested_by_name"] == "olivia" and card["ticket_subject"]
    decided = decide(client, card["approval_id"], "approve").json()
    assert decided["decided_by_name"] == "sam"
