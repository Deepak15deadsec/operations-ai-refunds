"""Chat model factory plus two deterministic, offline models.

- `ScriptedChatModel` replays a fixed list of AI messages (unit tests and evaluations).
- `DemoHeuristicModel` ("demo:heuristic") is a rule-based stand-in for a real LLM, so the whole
  product can be demonstrated and E2E-tested without a provider key. It calls the same tools and
  returns the same structured output a real model would. It is clearly labelled in the UI.
"""

import json
import os
import re
import uuid
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

RESULT_TOOL = "InvestigationResult"

_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google_genai": "GOOGLE_API_KEY",
}


class AgentConfigError(RuntimeError):
    """The configured model cannot be used (missing key, unknown provider). Not retryable."""


class _ToolBindingModel(BaseChatModel):
    def bind_tools(self, tools: Sequence[Any], **kwargs: Any):  # type: ignore[override]
        return self


class ScriptedChatModel(_ToolBindingModel):
    script: list[AIMessage]
    position: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        if self.position >= len(self.script):
            message = AIMessage(content="I have nothing further to add.")
        else:
            message = self.script[self.position]
            self.position += 1
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"}


def tool_output(message: ToolMessage) -> dict[str, Any]:
    """Tool results arrive as JSON text (direct tools) or MCP text content blocks."""
    content = message.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, json.JSONDecodeError):
        return {"error": "unparseable_tool_output", "raw": str(content)[:500]}


class DemoHeuristicModel(_ToolBindingModel):
    @property
    def _llm_type(self) -> str:
        return "demo-heuristic"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        human = next((m for m in messages if isinstance(m, HumanMessage)), None)
        match = re.search(r"T-\d+", str(human.content) if human else "")
        ticket_number = match.group(0) if match else "T-0"
        results: dict[str, dict[str, Any]] = {}
        for m in messages:
            if isinstance(m, ToolMessage) and m.name:
                results[m.name] = tool_output(m)

        if "get_ticket" not in results:
            return AIMessage(content="", tool_calls=[tool_call("get_ticket", {"ticket_number": ticket_number})])
        ticket = results["get_ticket"]
        order_number = ticket.get("order_number")
        if "error" in ticket or not order_number:
            return self._final(ticket_number, ticket, None, None, None)
        needed = [
            ("get_order", {"order_number": order_number}),
            ("get_delivery_events", {"order_number": order_number}),
            ("get_refund_policy", {}),
        ]
        missing = [tool_call(n, a) for n, a in needed if n not in results]
        if missing:
            return AIMessage(content="", tool_calls=missing)
        return self._final(
            ticket_number, ticket, results["get_order"], results["get_delivery_events"], results["get_refund_policy"]
        )

    @staticmethod
    def _final(ticket_number, ticket, order, deliveries, policy) -> AIMessage:
        findings: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        if "error" in ticket:
            summary = f"Ticket {ticket_number} could not be retrieved ({ticket['error']}); no action proposed."
            proposals.append({"action_type": "no_action", "ticket_number": ticket_number,
                              "reason": "Ticket not found"} if re.fullmatch(r"T-\d+", ticket_number) else {})
            proposals = [p for p in proposals if p]
            result = {"ticket_number": ticket_number if re.fullmatch(r"T-\d+", ticket_number) else "T-0",
                      "summary": summary, "findings": [], "proposals": proposals,
                      "requires_human_followup": True}
            return AIMessage(content="", tool_calls=[tool_call(RESULT_TOOL, result)])

        findings.append({"claim": f"Ticket subject: {ticket.get('subject', '')[:200]}",
                         "source_type": "ticket", "source_id": ticket_number})
        if order is None or "error" in (order or {}):
            summary = "The ticket has no retrievable order; escalating for a human to review."
            proposals.append({"action_type": "escalate_ticket", "ticket_number": ticket_number,
                              "reason": "No linked order could be verified"})
        else:
            on = order["order_number"]
            overdue = float(order.get("days_past_promised_delivery") or 0)
            findings.append({"claim": f"Order is {order['payment_status']} and {order['shipping_status']}; "
                                      f"{overdue:.1f} days past promised delivery",
                             "source_type": "order", "source_id": on})
            if deliveries and deliveries.get("events"):
                last = deliveries["events"][-1]
                findings.append({"claim": f"Latest delivery event: {last['event_type']} - "
                                          f"{last['description'][:150]}",
                                 "source_type": "delivery_event", "source_id": on})
            min_days = int(policy.get("min_delay_days", 5)) if policy else 5
            percent = int(policy.get("refund_percent", 0)) if policy else 0
            if policy and "error" not in policy:
                findings.append({"claim": f"Policy {policy['version']}: refund {percent}% when delayed "
                                          f"at least {min_days} days",
                                 "source_type": "policy", "source_id": policy["version"]})
            eligible = (
                order["payment_status"] == "paid"
                and order["shipping_status"] == "delayed"
                and not order.get("actual_delivery_at")
                and overdue >= min_days
                and not order.get("refunded")
                and percent > 0
            )
            text = (ticket.get("subject", "") + " " + ticket.get("description", "")).lower()
            if eligible:
                amount = order["total_amount_minor"] * percent // 100
                summary = (f"Order {on} is paid and delayed {overdue:.0f} days past the promised date, "
                           f"which exceeds the {min_days}-day policy threshold. A refund is proposed.")
                proposals.append({"action_type": "refund", "order_number": on, "amount_minor": amount,
                                  "currency": order["currency"],
                                  "reason": "Delayed delivery beyond policy threshold"})
                rupees = f"{amount / 100:,.2f}"
                proposals.append({
                    "action_type": "send_reply", "ticket_number": ticket_number,
                    "message_body": (
                        f"Hello {order.get('customer_name') or 'there'}, we're sorry your order {on} is "
                        f"delayed. Because the delay exceeds our policy, we have proposed a full refund "
                        f"of INR {rupees}. You will receive a confirmation once it is processed."),
                    "reason": "Explain the proposed resolution to the customer"})
            elif any(w in text for w in ("damaged", "broken", "wrong item")):
                summary = f"Order {on} is not eligible for a delay refund, but the customer reports a problem "\
                          "that needs human review."
                proposals.append({"action_type": "escalate_ticket", "ticket_number": ticket_number,
                                  "reason": "Customer reports damaged or wrong item; outside refund policy"})
            else:
                why = "already refunded" if order.get("refunded") else (
                    f"payment {order['payment_status']}, shipping {order['shipping_status']}, "
                    f"{overdue:.1f} days past promised delivery (threshold {min_days})")
                summary = f"Order {on} does not qualify for a refund under the active policy ({why})."
                proposals.append({"action_type": "no_action", "ticket_number": ticket_number,
                                  "reason": f"Not eligible: {why}"})
        result = {"ticket_number": ticket_number, "summary": summary, "findings": findings[:20],
                  "proposals": proposals, "requires_human_followup": False}
        return AIMessage(content="", tool_calls=[tool_call(RESULT_TOOL, result)])


def build_chat_model(model_name: str) -> BaseChatModel:
    if model_name in ("demo:heuristic", "demo"):
        return DemoHeuristicModel()
    provider, _, name = model_name.partition(":")
    if not name:
        raise AgentConfigError(f"AGENT_MODEL must look like 'provider:model', got {model_name!r}")
    key_var = _PROVIDER_KEYS.get(provider)
    if key_var and not os.environ.get(key_var):
        raise AgentConfigError(f"AGENT_MODEL uses {provider} but {key_var} is not set")
    try:
        from langchain.chat_models import init_chat_model

        return init_chat_model(model_name, temperature=0, timeout=60, max_retries=2)  # type: ignore[return-value]
    except Exception as exc:  # unknown provider / missing integration package
        raise AgentConfigError(f"Cannot initialise model {model_name!r}: {exc}") from exc
