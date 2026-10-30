"""Durable one-ticket workflow.

load_context -> investigate -> validate_proposals -> persist_proposals
    -> await_approval (interrupt) -> reverify -> execute -> (loop while approvals pending) -> summarize

Every node is safe to re-run: DB writes are idempotent or guarded by status checks, and the only
side-effecting step (execute) goes through the idempotent executor in its own transaction.
"""

import asyncio
import logging
import uuid
from dataclasses import asdict
from typing import Any, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select

from app.agent.investigator import investigate
from app.agent.models import AgentConfigError, build_chat_model
from app.agent.tools import ToolProvider, default_tool_provider
from app.core.config import get_settings
from app.db.models import AgentRun, ApprovalRequest, ProposedAction, Ticket
from app.db.session import transaction
from app.schemas.investigation import InvestigationResult, NoActionProposal
from app.services import audit, events, proposals
from app.services.approvals import TERMINAL_RUN_STATUSES
from app.services.executor import execute_action
from app.services.runs import aggregate_batch_status, set_status

log = logging.getLogger(__name__)

HUMAN_REVIEW_ERRORS = {"invalid_structured_output", "no_structured_output", "ticket_mismatch"}


class RunState(TypedDict):
    run_id: str
    tenant_id: str
    ticket_number: NotRequired[str]
    instruction: NotRequired[str]
    investigation: NotRequired[dict[str, Any] | None]
    validated: NotRequired[list[dict[str, Any]]]
    error_code: NotRequired[str | None]
    error_message: NotRequired[str | None]
    stop: NotRequired[bool]


class WorkflowDeps:
    """Injectable dependencies (tests swap the model and tool provider)."""

    model_factory = staticmethod(build_chat_model)
    tool_provider: ToolProvider | None = None

    @classmethod
    def tools(cls) -> ToolProvider:
        return cls.tool_provider or default_tool_provider()


def _ids(state: RunState) -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.UUID(state["run_id"]), uuid.UUID(state["tenant_id"])


def _sink(run_id: uuid.UUID, tenant_id: uuid.UUID):
    def sink(event_type: str, payload: dict[str, Any]) -> None:
        with transaction() as session:
            events.emit(session, tenant_id=tenant_id, run_id=run_id, event_type=event_type, payload=payload)

    return sink


def _actions(session, run_id: uuid.UUID) -> list[ProposedAction]:
    return list(session.scalars(select(ProposedAction).where(ProposedAction.run_id == run_id)))


# ---------------------------------------------------------------- nodes


def load_context(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return {"stop": True}
        ticket = session.get(Ticket, run.ticket_id) if run.ticket_id else None
        if ticket is None:
            return {"stop": True}
        set_status(session, run, "running")
        return {"ticket_number": ticket.ticket_number, "instruction": run.original_instruction, "stop": False}


def investigate_node(state: RunState) -> dict[str, Any]:
    run_id, tenant_id = _ids(state)
    settings = get_settings()
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        if run.status in TERMINAL_RUN_STATUSES:
            return {"stop": True}
        set_status(session, run, "investigating")

    try:
        model = WorkflowDeps.model_factory(settings.agent_model)
    except AgentConfigError as exc:
        return {"investigation": None, "error_code": "llm_not_configured", "error_message": str(exc)}

    outcome = asyncio.run(
        investigate(
            tenant_id=tenant_id,
            run_id=run_id,
            ticket_number=state["ticket_number"],
            instruction=state["instruction"],
            model=model,
            model_name=settings.agent_model,
            tool_provider=WorkflowDeps.tools(),
            sink=_sink(run_id, tenant_id),
        )
    )
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        run.usage = outcome.usage
        if outcome.result is not None:
            run.findings = outcome.result.model_dump(mode="json")
            events.emit(session, tenant_id=tenant_id, run_id=run_id, event_type="investigation_completed",
                        payload={"summary": outcome.result.summary,
                                 "proposal_types": [p.action_type for p in outcome.result.proposals],
                                 "usage": outcome.usage})
    return {
        "investigation": outcome.result.model_dump(mode="json") if outcome.result else None,
        "error_code": outcome.error_code,
        "error_message": outcome.error_message,
    }


def validate_proposals(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    result = InvestigationResult.model_validate(state["investigation"])
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        set_status(session, run, "validating")
        ticket = session.get(Ticket, run.ticket_id)
        assert ticket is not None
        validated = proposals.validate(session, ticket, result)
    return {"validated": [asdict(v) for v in validated]}


def persist_proposals(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    result = InvestigationResult.model_validate(state["investigation"])
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        ticket = session.get(Ticket, run.ticket_id)
        assert ticket is not None
        validated = [proposals.Validated(**v) for v in state.get("validated", [])]
        proposals.persist(session, run, ticket, result, validated)
    return {}


def await_approval(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        if run.status in TERMINAL_RUN_STATUSES:
            return {"stop": True}
        pending = [str(a.id) for a in _actions(session, run_id) if a.status == "pending_approval"]
        if pending:
            set_status(session, run, "awaiting_approval", pending_action_ids=pending)
    if not pending:
        return {}
    # Checkpointed here. The resume value is informational only: authorization is re-read from the DB.
    interrupt({"pending_action_ids": pending})
    return {}


def reverify(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        if run.status in TERMINAL_RUN_STATUSES:
            return {"stop": True}
        set_status(session, run, "resuming")
    return {}


def execute(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    with transaction() as session:
        approved = [a.id for a in _actions(session, run_id) if a.status == "approved"]
        if approved:
            run = session.get(AgentRun, run_id)
            assert run is not None
            set_status(session, run, "executing")
    for action_id in approved:
        with transaction() as session:  # one transaction per effect
            outcome = execute_action(session, action_id)
            log.info("executed action", extra={"run_id": run_id, "action_id": action_id,
                                                "status": outcome.status})
    return {}


def _finish(session, run: AgentRun, status: str, summary: dict[str, Any]) -> None:
    run.summary = summary
    set_status(session, run, status)
    audit.record(session, tenant_id=run.tenant_id, actor_type="system", actor_id="workflow", run_id=run.id,
                 event_type="run_finished", metadata={"status": status, "error_code": run.error_code})
    events.emit(session, tenant_id=run.tenant_id, run_id=run.id, event_type="run_completed",
                payload={"status": status, "summary": summary.get("text")})
    if run.parent_run_id:
        parent = session.scalar(select(AgentRun).where(AgentRun.id == run.parent_run_id).with_for_update())
        if parent is not None and parent.status not in TERMINAL_RUN_STATUSES:
            children = list(session.scalars(select(AgentRun).where(AgentRun.parent_run_id == parent.id)))
            set_status(session, parent, aggregate_batch_status(children))


def summarize(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    with transaction() as session:
        run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        assert run is not None
        if run.status in TERMINAL_RUN_STATUSES:
            return {}
        actions = _actions(session, run_id)
        approvals = {
            a.action_id: a
            for a in session.scalars(
                select(ApprovalRequest).where(ApprovalRequest.action_id.in_([x.id for x in actions]))
            )
        }
        statuses = [a.status for a in actions]
        executed_failure = [a for a in actions if a.status in ("failed", "needs_review") and a.id in approvals]
        if "completed" in statuses:
            status = "completed"
        elif any(a.status == "needs_review" for a in executed_failure):
            status = "needs_human_review"
        elif executed_failure:
            status = "failed"
        elif actions and all(s in ("rejected", "expired") for s in statuses if s != "failed") and any(
            s in ("rejected", "expired") for s in statuses
        ):
            status = "rejected"
        else:
            status = "completed_no_action"

        investigation = state.get("investigation") or {}
        no_action_reasons = [
            p.reason for p in InvestigationResult.model_validate(investigation).proposals
            if isinstance(p, NoActionProposal)
        ] if investigation else []
        summary = {
            "text": investigation.get("summary"),
            "requires_human_followup": investigation.get("requires_human_followup", False),
            "no_action_reasons": no_action_reasons,
            "actions": [
                {"action_id": str(a.id), "action_type": a.action_type, "status": a.status,
                 "status_reason": a.status_reason}
                for a in actions
            ],
        }
        _finish(session, run, status, summary)
    return {}


def fail_run(state: RunState) -> dict[str, Any]:
    run_id, _ = _ids(state)
    code = state.get("error_code") or "unknown_error"
    with transaction() as session:
        run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        assert run is not None
        if run.status in TERMINAL_RUN_STATUSES:
            return {}
        run.error_code = code
        run.error_message = state.get("error_message")
        status = "needs_human_review" if code in HUMAN_REVIEW_ERRORS else "failed"
        _finish(session, run, status, {"text": None, "error_code": code, "error_message": run.error_message,
                                       "actions": []})
    return {}


# ---------------------------------------------------------------- routing


def _after_load(state: RunState) -> str:
    return END if state.get("stop") else "investigate"


def _after_investigate(state: RunState) -> str:
    if state.get("stop"):
        return END
    return "validate_proposals" if state.get("investigation") else "fail_run"


def _next_after_actions(state: RunState) -> str:
    if state.get("stop"):
        return END
    run_id, _ = _ids(state)
    with transaction() as session:
        statuses = {a.status for a in _actions(session, run_id)}
    if "pending_approval" in statuses:
        return "await_approval"
    if "approved" in statuses:
        return "reverify"
    return "summarize"


def _after_await(state: RunState) -> str:
    return END if state.get("stop") else "reverify"


def _after_reverify(state: RunState) -> str:
    return END if state.get("stop") else "execute"


def build_graph(checkpointer=None):
    graph = StateGraph(RunState)
    graph.add_node("load_context", load_context)
    graph.add_node("investigate", investigate_node)
    graph.add_node("validate_proposals", validate_proposals)
    graph.add_node("persist_proposals", persist_proposals)
    graph.add_node("await_approval", await_approval)
    graph.add_node("reverify", reverify)
    graph.add_node("execute", execute)
    graph.add_node("summarize", summarize)
    graph.add_node("fail_run", fail_run)

    graph.add_edge(START, "load_context")
    graph.add_conditional_edges("load_context", _after_load, ["investigate", END])
    graph.add_conditional_edges("investigate", _after_investigate, ["validate_proposals", "fail_run", END])
    graph.add_edge("validate_proposals", "persist_proposals")
    graph.add_conditional_edges("persist_proposals", _next_after_actions,
                                ["await_approval", "reverify", "summarize", END])
    graph.add_conditional_edges("await_approval", _after_await, ["reverify", END])
    graph.add_conditional_edges("reverify", _after_reverify, ["execute", END])
    graph.add_conditional_edges("execute", _next_after_actions, ["await_approval", "reverify", "summarize", END])
    graph.add_edge("summarize", END)
    graph.add_edge("fail_run", END)
    return graph.compile(checkpointer=checkpointer)
