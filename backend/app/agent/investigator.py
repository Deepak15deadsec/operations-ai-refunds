"""Runs the read-only investigation agent for one ticket and returns a validated result."""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware, ToolRetryMiddleware
from langchain.agents.structured_output import StructuredOutputError, ToolStrategy
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.agent.prompts import SYSTEM_PROMPT, user_prompt
from app.agent.tools import ToolProvider
from app.core.config import get_settings
from app.schemas.investigation import InvestigationResult

log = logging.getLogger(__name__)
EventSink = Callable[[str, dict[str, Any]], None]
TRANSIENT_TOOL_ERRORS = (TimeoutError, ConnectionError, httpx.TransportError)


@dataclass
class InvestigationOutcome:
    result: InvestigationResult | None
    error_code: str | None = None
    error_message: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class ToolTracer(BaseCallbackHandler):
    """Persists tool start/end/error events for the run timeline (inputs truncated, no secrets)."""

    def __init__(self, sink: EventSink):
        self.sink = sink
        self.started: dict[uuid.UUID, tuple[str, float]] = {}
        self.calls = 0
        self.errors = 0

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: uuid.UUID, **kwargs: Any):
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        self.started[run_id] = (name, time.monotonic())
        self.calls += 1
        self.sink("tool_started", {"tool": name, "input": str(kwargs.get("inputs") or input_str)[:300]})

    def on_tool_end(self, output: Any, *, run_id: uuid.UUID, **kwargs: Any):
        name, t0 = self.started.pop(run_id, ("tool", time.monotonic()))
        content = getattr(output, "content", output)
        is_error = '"error"' in str(content)[:200]
        self.sink("tool_completed", {"tool": name, "duration_ms": int((time.monotonic() - t0) * 1000),
                                     "result_preview": str(content)[:300], "domain_error": is_error})

    def on_tool_error(self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any):
        name, t0 = self.started.pop(run_id, ("tool", time.monotonic()))
        self.errors += 1
        self.sink("tool_failed", {"tool": name, "duration_ms": int((time.monotonic() - t0) * 1000),
                                  "error": type(error).__name__, "message": str(error)[:300]})


def _usage(messages: list[Any], model_name: str, tracer: ToolTracer, elapsed: float) -> dict[str, Any]:
    tokens_in = tokens_out = 0
    for m in messages:
        meta = getattr(m, "usage_metadata", None) if isinstance(m, AIMessage) else None
        if meta:
            tokens_in += meta.get("input_tokens", 0)
            tokens_out += meta.get("output_tokens", 0)
    return {"model": model_name, "input_tokens": tokens_in, "output_tokens": tokens_out,
            "tool_calls": tracer.calls, "tool_errors": tracer.errors, "duration_ms": int(elapsed * 1000)}


async def investigate(
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    ticket_number: str,
    instruction: str,
    model: BaseChatModel,
    model_name: str,
    tool_provider: ToolProvider,
    sink: EventSink,
) -> InvestigationOutcome:
    settings = get_settings()
    tracer = ToolTracer(sink)
    structured_retries = {"count": 0}

    def on_structured_error(exc: Exception) -> str:
        # Retry once with validation feedback, then give up (-> needs human review).
        structured_retries["count"] += 1
        if structured_retries["count"] > 1:
            raise exc
        sink("structured_output_retry", {"error": str(exc)[:300]})
        return f"Your structured result was invalid: {str(exc)[:1000]}. Return a corrected InvestigationResult."

    started = time.monotonic()
    messages: list[Any] = []
    tools_loaded = False
    middleware: list[Any] = [
        ToolCallLimitMiddleware(run_limit=settings.agent_max_tool_calls, exit_behavior="continue"),
        ModelCallLimitMiddleware(run_limit=settings.agent_max_model_calls, exit_behavior="end"),
        ToolRetryMiddleware(max_retries=2, retry_on=TRANSIENT_TOOL_ERRORS, initial_delay=0.2,
                            max_delay=2.0, jitter=True, on_failure="continue"),
    ]
    try:
        async with tool_provider.tools(tenant_id, run_id) as tools:
            tools_loaded = True
            agent = create_agent(
                model,
                tools=tools,
                system_prompt=SYSTEM_PROMPT,
                # Not a durable subgraph: re-running a read-only investigation is safe, and the
                # parent workflow checkpoints its result.
                checkpointer=False,
                response_format=ToolStrategy(InvestigationResult, handle_errors=on_structured_error),
                middleware=middleware,
            )
            state = await asyncio.wait_for(
                agent.ainvoke(
                    {"messages": [{"role": "user", "content": user_prompt(ticket_number, instruction)}]},
                    config={"callbacks": [tracer], "recursion_limit": 60},
                ),
                timeout=settings.agent_timeout_seconds,
            )
            messages = state.get("messages", [])
            result = state.get("structured_response")
    except TimeoutError:
        return InvestigationOutcome(None, "agent_timeout", "Investigation exceeded its time budget",
                                    _usage(messages, model_name, tracer, time.monotonic() - started))
    except (StructuredOutputError, ValidationError, ValueError) as exc:
        return InvestigationOutcome(None, "invalid_structured_output", str(exc)[:500],
                                    _usage(messages, model_name, tracer, time.monotonic() - started))
    except Exception as exc:  # provider outage, MCP unavailable, ...
        log.exception("investigation failed", extra={"run_id": run_id})
        # Fail closed: if the read tools could not be loaded, nothing is fabricated.
        code = "llm_error" if tools_loaded else "tools_unavailable"
        return InvestigationOutcome(None, code, f"{type(exc).__name__}: {str(exc)[:400]}",
                                    _usage(messages, model_name, tracer, time.monotonic() - started))

    usage = _usage(messages, model_name, tracer, time.monotonic() - started)
    if not isinstance(result, InvestigationResult):
        return InvestigationOutcome(None, "no_structured_output",
                                    "The model did not return a structured investigation result", usage)
    if result.ticket_number != ticket_number:
        return InvestigationOutcome(None, "ticket_mismatch",
                                    f"Result is about {result.ticket_number}, expected {ticket_number}", usage)
    return InvestigationOutcome(result, usage=usage)
