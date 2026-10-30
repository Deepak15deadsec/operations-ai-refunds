"""Shared fixtures: real PostgreSQL (migrated with Alembic), fixed clock, signed test tokens,
scripted LLM, and an inline worker. No LLM key or network access is needed."""

import os
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://app:local_only@localhost:55432/operations_test")
os.environ.update({
    "DATABASE_URL": TEST_DB,
    "MCP_DATABASE_URL": TEST_DB,
    "LANGGRAPH_DATABASE_URL": TEST_DB.replace("postgresql+psycopg://", "postgresql://")
    + "?options=-csearch_path%3Dlanggraph",
    "OIDC_ISSUER_URL": "http://test-issuer/realms/operations-demo",
    "OIDC_AUDIENCE": "operations-api",
    "AGENT_MODEL": "scripted:test",
    "AGENT_TOOL_TRANSPORT": "direct",
    "AGENT_TIMEOUT_SECONDS": "20",
    "MCP_RUN_TOKEN_SECRET": "test-secret-for-run-tokens-0123456789",
    "RUNS_PER_MINUTE_PER_USER": "1000",
    "LOG_LEVEL": "WARNING",
})

import jwt  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.agent.models import ScriptedChatModel, tool_call  # noqa: E402
from app.core import auth  # noqa: E402
from app.core.clock import set_clock  # noqa: E402
from app.db.models import WorkerJob  # noqa: E402
from app.db.seed import ACME, GLOBEX, seed  # noqa: E402
from app.db.session import transaction  # noqa: E402
from app.services import jobs  # noqa: E402
from app.worker.main import Worker  # noqa: E402
from app.workflow.checkpoint import make_checkpointer, open_pool, setup_checkpointer  # noqa: E402
from app.workflow.graph import WorkflowDeps, build_graph  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
BACKEND = Path(__file__).resolve().parents[1]
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE; DROP SCHEMA IF EXISTS langgraph CASCADE; "
                          "CREATE SCHEMA public;"))
    engine.dispose()
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    setup_checkpointer()
    yield


@pytest.fixture(autouse=True)
def fixtures(database) -> Iterator[None]:
    set_clock(lambda: NOW)
    with transaction() as session:
        seed(session, NOW)
    auth.set_key_resolver(auth.StaticKeyResolver(_PRIVATE_KEY.public_key()))
    WorkflowDeps.tool_provider = None
    yield
    set_clock(None)
    WorkflowDeps.model_factory = staticmethod(lambda name: ScriptedChatModel(script=[]))


def make_token(
    roles: list[str],
    tenant_id: uuid.UUID | str | None = ACME,
    sub: str | None = None,
    *,
    audience: str = "operations-api",
    issuer: str = "http://test-issuer/realms/operations-demo",
    expires_in: int = 300,
    key=None,
) -> str:
    now = int(time.time())
    claims = {
        "iss": issuer, "aud": audience, "sub": sub or f"user-{'-'.join(roles)}", "iat": now,
        "exp": now + expires_in, "realm_access": {"roles": roles}, "preferred_username": sub or roles[0],
    }
    if tenant_id is not None:
        claims["tenant_id"] = str(tenant_id)
    return jwt.encode(claims, key or _PRIVATE_KEY, algorithm="RS256")


def bearer(*roles: str, tenant_id=ACME, sub: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(list(roles), tenant_id, sub)}"}


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


OPERATOR = lambda: bearer("operator", sub="olivia")  # noqa: E731
SUPERVISOR = lambda: bearer("supervisor", sub="sam")  # noqa: E731
ADMIN = lambda: bearer("admin", sub="ada")  # noqa: E731
GLOBEX_SUPERVISOR = lambda: bearer("supervisor", tenant_id=GLOBEX, sub="gus")  # noqa: E731


# ------------------------------------------------------------------ scripted model helpers


def investigation_script(ticket: str, order: str | None, proposals: list[dict], summary: str = "Investigated.",
                         findings: list[dict] | None = None) -> list[AIMessage]:
    calls = [AIMessage(content="", tool_calls=[tool_call("get_ticket", {"ticket_number": ticket})])]
    if order:
        calls.append(AIMessage(content="", tool_calls=[
            tool_call("get_order", {"order_number": order}),
            tool_call("get_delivery_events", {"order_number": order}),
            tool_call("get_refund_policy", {}),
        ]))
    result = {
        "ticket_number": ticket, "summary": summary,
        "findings": findings if findings is not None else (
            [{"claim": "Order is delayed", "source_type": "order", "source_id": order}] if order else []),
        "proposals": proposals, "requires_human_followup": False,
    }
    calls.append(AIMessage(content="", tool_calls=[tool_call("InvestigationResult", result)]))
    return calls


def refund(order: str, amount: int) -> dict:
    return {"action_type": "refund", "order_number": order, "amount_minor": amount, "currency": "INR",
            "reason": "Delayed delivery beyond policy threshold"}


def reply(ticket: str, body: str = "Sorry for the delay. We have proposed a refund for your order.") -> dict:
    return {"action_type": "send_reply", "ticket_number": ticket, "message_body": body,
            "reason": "Explain the proposed resolution"}


def use_script(script: list[AIMessage]) -> None:
    WorkflowDeps.model_factory = staticmethod(lambda name: ScriptedChatModel(script=list(script)))


def use_model(factory: Callable) -> None:
    WorkflowDeps.model_factory = staticmethod(factory)


# ------------------------------------------------------------------ worker helpers


@pytest.fixture
def checkpoint_pool():
    pool = open_pool(max_size=4)
    yield pool
    pool.close()


@pytest.fixture
def graph(checkpoint_pool):
    return build_graph(make_checkpointer(checkpoint_pool))


def drain(graph, max_jobs: int = 50) -> int:
    """Process due jobs inline (deterministic stand-in for the worker loop)."""
    worker = Worker(graph, concurrency=1, owner="test-worker")
    processed = 0
    while processed < max_jobs:
        with transaction() as session:
            job = jobs.claim(session, worker.owner)
            job_id = job.id if job else None
        if job_id is None:
            break
        worker.process(job_id)
        processed += 1
    worker.pool.shutdown(wait=False)
    return processed


def job_rows(run_id) -> list[WorkerJob]:
    with transaction() as session:
        rows = list(session.query(WorkerJob).filter(WorkerJob.run_id == run_id))
        for r in rows:
            session.expunge(r)
        return rows


def count(sql: str, **params) -> int:
    with transaction() as session:
        return int(session.execute(text(sql), params).scalar() or 0)
