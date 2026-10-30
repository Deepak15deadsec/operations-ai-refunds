"""Worker process: claims jobs from PostgreSQL, runs graphs, sweeps expired approvals.

Run with `python -m app.worker.main`. Safe to run several instances; leases + SKIP LOCKED ensure a
job is processed by one worker at a time, and idempotent effects make lease-expiry retries safe.
"""

import logging
import os
import signal
import socket
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import WorkerJob
from app.db.session import transaction
from app.services import approvals, jobs
from app.worker.runner import mark_run_failed, run_job
from app.workflow.checkpoint import make_checkpointer, open_pool
from app.workflow.graph import build_graph

log = logging.getLogger("worker")


class Worker:
    def __init__(self, graph, concurrency: int | None = None, owner: str | None = None):
        settings = get_settings()
        self.graph = graph
        self.settings = settings
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.concurrency = concurrency or settings.max_concurrent_ticket_runs
        self.pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="job")
        self.active: set[Future] = set()
        self.stopping = threading.Event()
        self._last_sweep = 0.0

    # -- one job, with lease heartbeat
    def process(self, job_id: uuid.UUID) -> None:
        with transaction() as session:
            job = session.get(WorkerJob, job_id)
            assert job is not None
            session.expunge(job)
        stop_heartbeat = threading.Event()

        def heartbeat() -> None:
            interval = max(5, self.settings.worker_lease_seconds // 3)
            while not stop_heartbeat.wait(interval):
                with transaction() as session:
                    jobs.extend_lease(session, job.id, self.owner, self.settings.worker_lease_seconds)

        beat = threading.Thread(target=heartbeat, daemon=True)
        beat.start()
        try:
            result = run_job(self.graph, job)
            with transaction() as session:
                if result.status == "retry_later":
                    jobs.reschedule(session, job.id, self.owner, result.delay_seconds, consume=False)
                else:
                    jobs.complete(session, job.id, self.owner)
        except Exception as exc:
            log.exception("job failed", extra={"job_id": job.id, "run_id": job.run_id})
            message = f"{type(exc).__name__}: {exc}"
            with transaction() as session:
                if job.attempts < job.max_attempts:
                    backoff = min(60, 2 ** job.attempts)
                    jobs.record_error(session, job.id, message)
                    jobs.reschedule(session, job.id, self.owner, backoff, consume=True)
                else:
                    jobs.fail(session, job.id, self.owner, message)
            if job.attempts >= job.max_attempts:
                mark_run_failed(job.run_id, "worker_error", message)
        finally:
            stop_heartbeat.set()

    def sweep(self) -> None:
        if time.monotonic() - self._last_sweep < self.settings.worker_sweep_seconds:
            return
        self._last_sweep = time.monotonic()
        with transaction() as session:
            expired = approvals.expire_due(session)
        if expired:
            log.info("expired approvals", extra={"count": expired})

    def tick(self) -> bool:
        """Claim and dispatch at most one job. Returns True if a job was dispatched."""
        self.active = {f for f in self.active if not f.done()}
        if len(self.active) >= self.concurrency:
            return False
        with transaction() as session:
            job = jobs.claim(session, self.owner)
            job_id = job.id if job else None
        if job_id is None:
            return False
        self.active.add(self.pool.submit(self.process, job_id))
        return True

    def run_forever(self) -> None:
        log.info("worker started", extra={"job_id": self.owner})
        while not self.stopping.is_set():
            try:
                self.sweep()
                if not self.tick():
                    self.stopping.wait(self.settings.worker_poll_seconds)
            except Exception:
                log.exception("worker loop error")
                self.stopping.wait(2)
        self.pool.shutdown(wait=True)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    pool = open_pool(max_size=settings.max_concurrent_ticket_runs + 2)
    worker = Worker(build_graph(make_checkpointer(pool)))
    signal.signal(signal.SIGTERM, lambda *_: worker.stopping.set())
    signal.signal(signal.SIGINT, lambda *_: worker.stopping.set())
    try:
        worker.run_forever()
    finally:
        pool.close()


if __name__ == "__main__":
    main()
