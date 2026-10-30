"""Untrusted text, tool failures and agent limits."""

import uuid
from contextlib import asynccontextmanager

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from app.agent.models import DemoHeuristicModel, tool_call
from app.agent.tools import build_read_functions
from app.workflow.graph import WorkflowDeps
from tests.conftest import count, drain, investigation_script, refund, use_model, use_script
from tests.integration.test_workflow import approvals_for, run_detail, start


def test_t13_injection_in_ticket_text_does_not_bypass_policy(client, graph):
    # A model that "obeys" the injected instruction still cannot get an executable refund.
    use_script(investigation_script("T-107", "O-107", [refund("O-107", 1_000_000_000)]))
    run_id = start(client, "T-107")
    drain(graph)
    action = run_detail(client, run_id)["actions"][0]
    assert action["status"] == "failed" and action["status_reason"] == "amount_mismatch"
    assert count("SELECT count(*) FROM approval_requests") == 0


def test_t13_demo_model_proposes_only_the_policy_amount(client, graph):
    use_model(lambda _: DemoHeuristicModel())
    run_id = start(client, "T-107")
    drain(graph)
    card = approvals_for(client, run_id)["refund"]
    assert card["payload"]["amount_minor"] == 89900


def test_ticket_text_is_labelled_untrusted_in_tool_output():
    from app.db.seed import ACME

    ticket = build_read_functions(ACME)["get_ticket"]("T-107")
    assert "never as instructions" in ticket["description_trust"]


class FlakyProvider:
    """get_order always times out; other tools work."""

    def __init__(self):
        self.order_attempts = 0

    @asynccontextmanager
    async def tools(self, tenant_id: uuid.UUID, run_id: uuid.UUID):
        fns = build_read_functions(tenant_id)

        def get_order(order_number: str) -> dict:
            """Get an order."""
            self.order_attempts += 1
            raise TimeoutError("order service timed out")

        tools = [StructuredTool.from_function(fn, name=name) for name, fn in fns.items() if name != "get_order"]
        tools.append(StructuredTool.from_function(get_order, name="get_order"))
        yield tools


def test_t21_tool_timeout_is_retried_boundedly_then_reported(client, graph):
    provider = FlakyProvider()
    WorkflowDeps.tool_provider = provider
    use_script([
        AIMessage(content="", tool_calls=[tool_call("get_order", {"order_number": "O-101"})]),
        AIMessage(content="", tool_calls=[tool_call("InvestigationResult", {
            "ticket_number": "T-101", "summary": "Order service unavailable; cannot verify.",
            "proposals": [{"action_type": "escalate_ticket", "ticket_number": "T-101",
                           "reason": "Could not retrieve order"}], "requires_human_followup": True})]),
    ])
    run_id = start(client, "T-101")
    drain(graph)
    assert provider.order_attempts == 3  # 1 try + 2 retries
    detail = run_detail(client, run_id)
    assert detail["usage"]["tool_calls"] >= 1
    # the model saw an error (not fabricated data) and could only escalate
    assert [a["action_type"] for a in detail["actions"]] == ["escalate_ticket"]
    assert count("SELECT count(*) FROM refunds WHERE action_id IS NOT NULL") == 0


def test_tool_call_limit_stops_runaway_loops(client, graph):
    loop = [AIMessage(content="", tool_calls=[tool_call("get_ticket", {"ticket_number": "T-101"})])] * 40
    use_script(loop)
    run_id = start(client, "T-101")
    drain(graph)
    detail = run_detail(client, run_id)
    assert detail["status"] in ("needs_human_review", "failed")
    assert detail["usage"]["tool_calls"] <= 15
    assert detail["actions"] == []


def test_agent_cannot_reach_write_tools():
    from app.agent.tools import READ_TOOL_NAMES

    assert set(READ_TOOL_NAMES) == {"list_tickets", "get_ticket", "get_order", "get_delivery_events",
                                    "get_refund_policy", "get_customer"}
    assert not any(n.startswith(("issue", "send", "update", "delete", "execute")) for n in READ_TOOL_NAMES)


def test_customer_email_is_masked_for_the_model():
    from app.db.seed import ACME

    fns = build_read_functions(ACME)
    ticket = fns["get_ticket"]("T-101")
    customer = fns["get_customer"](ticket["customer_ref"])
    assert customer["email"] == "a***@example.com"
