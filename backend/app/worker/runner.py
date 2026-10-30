"""Executes one claimed job: start/resume a run's graph, or fan out a batch."""

import logging
import uuid
from dataclasses import dataclass

from langgraph.types import Command
from sqlalchemy.orm import Session

from app.db.models import AgentRun, WorkerJob
from app.db.session import transaction
from app.services import approvals, runs
from app.services.approvals import TERMINAL_RUN_STATUSES

log = logging.getLogger(__name__)


@dataclass
class JobResult:
    status: str  # done | retry_later
    delay_seconds: float = 0.0


class NotReady(Exception):
    """The graph is not yet at an interrupt; try the resume again shortly."""


def _config(run: AgentRun) -> dict:
    return {"configurable": {"thread_id": run.thread_id}, "recursion_limit": 100}


def _load_run(session: Session, run_id: uuid.UUID | None) -> AgentRun | None:
    return session.get(AgentRun, run_id) if run_id else None


def run_start(graph, job: WorkerJob) -> JobResult:
    with transaction() as session:
        run = _load_run(session, job.run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return JobResult("done")
        if run.mode == "batch":
            runs.set_status(session, run, "running")
            children = runs.fan_out_batch(session, run)
            if not children:
                runs.set_status(session, run, "completed_no_action")
            return JobResult("done")
        config = _config(run)
        initial = {"run_id": str(run.id), "tenant_id": str(run.tenant_id)}

    snapshot = graph.get_state(config)
    if snapshot.interrupts:
        return JobResult("done")  # already waiting for approval (job retried after the interrupt)
    if snapshot.next:
        graph.invoke(None, config)  # resume from the last checkpoint after a crash
    else:
        graph.invoke(initial, config)
    return JobResult("done")


def run_resume(graph, job: WorkerJob) -> JobResult:
    with transaction() as session:
        run = _load_run(session, job.run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return JobResult("done")
        config = _config(run)

    snapshot = graph.get_state(config)
    if snapshot.interrupts:
        graph.invoke(Command(resume=job.payload), config)
        return JobResult("done")
    if snapshot.next:
        # Still investigating/persisting (or a crashed start job not yet retried): try later.
        return JobResult("retry_later", delay_seconds=2.0)
    return JobResult("done")  # graph already finished


def run_job(graph, job: WorkerJob) -> JobResult:
    if job.job_type == "start":
        return run_start(graph, job)
    if job.job_type == "resume":
        return run_resume(graph, job)
    if job.job_type == "expire_approvals":
        with transaction() as session:
            approvals.expire_due(session)
        return JobResult("done")
    raise ValueError(f"unknown job type {job.job_type}")


def mark_run_failed(run_id: uuid.UUID | None, error_code: str, message: str) -> None:
    if run_id is None:
        return
    with transaction() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        run.error_code = error_code
        run.error_message = message[:1000]
        runs.set_status(session, run, "failed")
