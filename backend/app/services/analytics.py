"""Agent observability: aggregate run telemetry into dashboard metrics.

All figures are derived from data the pipeline already records — `agent_runs.usage`
(model, tokens, tool calls, duration) and the per-tool `tool_completed` / `tool_failed`
timeline events — plus the simulated-effect tables. Every query is tenant-scoped.

This is a read-only aggregation. It never trusts the model's self-report for anything
that matters: the numbers here are the measured cost/latency/reliability of the agent,
not its opinions.
"""

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentEvent, AgentRun, OutboundMessage, ProposedAction, Refund

# Investigation-bearing runs. Batch *parent* runs only fan out children and carry no
# usage/events of their own, so they are excluded to avoid double counting.
INVESTIGATION_MODE = "ticket"

ACTIVE_STATUSES = frozenset(
    {"queued", "running", "investigating", "validating", "awaiting_approval", "resuming", "executing"}
)
# Maps a raw run status to the coarse outcome bucket shown on the dashboard.
OUTCOME_GROUP = {
    "completed": "completed",
    "completed_no_action": "no_action",
    "rejected": "rejected",
    "failed": "failed",
    "needs_human_review": "needs_review",
    "cancelled": "cancelled",
}

# Illustrative list prices in USD per 1M tokens (input, output), for an estimated spend
# figure. Offline models cost nothing. Clearly labelled as an estimate in the UI; a model
# that is not in this table contributes tokens but no cost, and marks the total "partial".
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "demo:heuristic": (0.0, 0.0),
    "scripted:test": (0.0, 0.0),
    "openai:gpt-4.1-mini": (0.40, 1.60),
    "openai:gpt-4.1": (2.00, 8.00),
    "openai:gpt-4.1-nano": (0.10, 0.40),
    "openai:gpt-4o-mini": (0.15, 0.60),
    "openai:gpt-4o": (2.50, 10.00),
    "anthropic:claude-3-5-haiku-latest": (0.80, 4.00),
    "anthropic:claude-3-5-sonnet-latest": (3.00, 15.00),
    "anthropic:claude-sonnet-4-latest": (3.00, 15.00),
}


def _pct(values: list[float], q: float) -> int:
    """Linear-interpolation percentile (same method as the evaluation runner)."""
    if not values:
        return 0
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo))


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    price = PRICING_USD_PER_MTOK.get(model)
    if price is None:
        return 0.0, False
    return input_tokens / 1_000_000 * price[0] + output_tokens / 1_000_000 * price[1], True


@dataclass
class _ModelAcc:
    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    durations: list[float] = field(default_factory=list)


@dataclass
class _ToolAcc:
    calls: int = 0
    errors: int = 0
    durations: list[float] = field(default_factory=list)


def agent_analytics(session: Session, tenant_id: uuid.UUID, window_hours: int | None = None) -> dict[str, Any]:
    # Reporting over server-stamped rows: use real wall-clock, consistent with created_at (func.now()).
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours) if window_hours else None

    run_stmt = select(AgentRun).where(
        AgentRun.tenant_id == tenant_id, AgentRun.mode == INVESTIGATION_MODE
    )
    if since is not None:
        run_stmt = run_stmt.where(AgentRun.created_at >= since)
    runs = list(session.scalars(run_stmt))

    by_status: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    active = 0
    durations: list[float] = []
    tokens_in = tokens_out = 0
    models: dict[str, _ModelAcc] = defaultdict(_ModelAcc)
    daily_runs: Counter[str] = Counter()
    daily_completed: Counter[str] = Counter()
    daily_failed: Counter[str] = Counter()

    for run in runs:
        by_status[run.status] += 1
        if run.status in ACTIVE_STATUSES:
            active += 1
            outcomes["active"] += 1
        else:
            outcomes[OUTCOME_GROUP.get(run.status, "other")] += 1

        day = run.created_at.date().isoformat()
        daily_runs[day] += 1
        if run.status == "completed":
            daily_completed[day] += 1
        elif run.status in ("failed", "needs_human_review"):
            daily_failed[day] += 1

        usage = run.usage or {}
        model = usage.get("model")
        duration = usage.get("duration_ms")
        in_tok = int(usage.get("input_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or 0)
        tokens_in += in_tok
        tokens_out += out_tok
        if duration is not None:
            durations.append(float(duration))
        if model:
            acc = models[model]
            acc.runs += 1
            acc.input_tokens += in_tok
            acc.output_tokens += out_tok
            if duration is not None:
                acc.durations.append(float(duration))

    finished = sum(c for s, c in by_status.items() if s not in ACTIVE_STATUSES)
    completed = by_status.get("completed", 0)

    # Per-tool reliability and latency from the timeline events.
    ev_stmt = select(AgentEvent).where(
        AgentEvent.tenant_id == tenant_id,
        AgentEvent.event_type.in_(["tool_completed", "tool_failed"]),
    )
    if since is not None:
        ev_stmt = ev_stmt.where(AgentEvent.created_at >= since)
    tools: dict[str, _ToolAcc] = defaultdict(_ToolAcc)
    for ev in session.scalars(ev_stmt):
        payload = ev.payload or {}
        name = payload.get("tool") or "unknown"
        tacc = tools[name]
        tacc.calls += 1
        if ev.event_type == "tool_failed" or payload.get("domain_error"):
            tacc.errors += 1
        dur = payload.get("duration_ms")
        if dur is not None:
            tacc.durations.append(float(dur))
    tool_calls = sum(t.calls for t in tools.values())
    tool_errors = sum(t.errors for t in tools.values())

    # Simulated effects the agent pipeline produced (seed fixtures carry no action_id).
    refund_stmt = select(func.count(), func.coalesce(func.sum(Refund.amount_minor), 0)).where(
        Refund.tenant_id == tenant_id, Refund.action_id.isnot(None))
    msg_stmt = select(func.count()).select_from(OutboundMessage).where(OutboundMessage.tenant_id == tenant_id)
    esc_stmt = select(func.count()).select_from(ProposedAction).where(
        ProposedAction.tenant_id == tenant_id,
        ProposedAction.action_type == "escalate_ticket",
        ProposedAction.status == "completed",
    )
    if since is not None:
        refund_stmt = refund_stmt.where(Refund.created_at >= since)
        msg_stmt = msg_stmt.where(OutboundMessage.created_at >= since)
        esc_stmt = esc_stmt.where(ProposedAction.created_at >= since)
    refund_count, refund_total = session.execute(refund_stmt).one()
    message_count = session.scalar(msg_stmt) or 0
    escalation_count = session.scalar(esc_stmt) or 0

    # Cost roll-up.
    est_cost = 0.0
    cost_complete = True
    model_rows: list[dict[str, Any]] = []
    for name, acc in sorted(models.items(), key=lambda kv: kv[1].runs, reverse=True):
        total_tokens = acc.input_tokens + acc.output_tokens
        cost, known = _cost_usd(name, acc.input_tokens, acc.output_tokens)
        est_cost += cost
        if total_tokens > 0 and not known:
            cost_complete = False
        model_rows.append({
            "model": name,
            "runs": acc.runs,
            "input_tokens": acc.input_tokens,
            "output_tokens": acc.output_tokens,
            "total_tokens": total_tokens,
            "avg_latency_ms": round(sum(acc.durations) / len(acc.durations)) if acc.durations else 0,
            "est_cost_usd": round(cost, 4),
            "cost_known": known,
        })

    tool_rows = [
        {
            "tool": name,
            "calls": acc.calls,
            "errors": acc.errors,
            "error_rate": round(acc.errors / acc.calls, 4) if acc.calls else 0.0,
            "p50_ms": _pct(acc.durations, 0.5),
            "p95_ms": _pct(acc.durations, 0.95),
        }
        for name, acc in sorted(tools.items(), key=lambda kv: kv[1].calls, reverse=True)
    ]

    # 14-day (or window-capped) daily series, oldest first, with gaps filled.
    span_days = min(14, (window_hours // 24) if window_hours else 14) or 1
    daily = []
    for i in range(span_days - 1, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        daily.append({
            "date": d,
            "runs": daily_runs.get(d, 0),
            "completed": daily_completed.get(d, 0),
            "failed": daily_failed.get(d, 0),
        })

    return {
        "generated_at": now,
        "window_hours": window_hours,
        "runs_total": len(runs),
        "runs_active": active,
        "runs_finished": finished,
        "by_status": dict(by_status),
        "outcomes": dict(outcomes),
        "success_rate": round(completed / finished, 4) if finished else 0.0,
        "latency": {
            "count": len(durations),
            "p50_ms": _pct(durations, 0.5),
            "p95_ms": _pct(durations, 0.95),
            "max_ms": round(max(durations)) if durations else 0,
        },
        "tokens_input": tokens_in,
        "tokens_output": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "est_cost_usd": round(est_cost, 4),
        "cost_complete": cost_complete,
        "tools_total_calls": tool_calls,
        "tools_total_errors": tool_errors,
        "tools_error_rate": round(tool_errors / tool_calls, 4) if tool_calls else 0.0,
        "tools": tool_rows,
        "models": model_rows,
        "refunds": refund_count,
        "refund_total_minor": int(refund_total),
        "messages": message_count,
        "escalations": escalation_count,
        "daily": daily,
    }
