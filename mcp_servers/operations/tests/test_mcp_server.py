"""MCP transport tests: a real streamable-HTTP server on a local port, called through
`langchain.mcp.MCPAdapter` exactly as the worker does."""

import asyncio
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn

from app.agent.tools import MCPToolProvider
from app.core import run_token
from app.db.seed import ACME, GLOBEX
from app.workflow.graph import WorkflowDeps
from tests.conftest import count, drain, investigation_script, refund, use_script
from tests.integration.test_workflow import approvals_for, run_detail, start


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_url():
    import os

    from app.core.config import get_settings

    port = _free_port()
    os.environ["MCP_ALLOWED_HOSTS"] = f"127.0.0.1:{port},localhost:{port}"
    get_settings.cache_clear()
    from operations_mcp.server import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def _tools(url: str, tenant=ACME, token_factory=None):
    provider = MCPToolProvider(url=url, token_factory=token_factory)
    async with provider.tools(tenant, uuid.uuid4()) as tools:
        return {t.name: t for t in tools}


def _call(url, tool, args, **kw):
    async def go():
        tools = await _tools(url, **kw)
        return await tools[tool].ainvoke(args)

    return asyncio.run(go())


def _text(result) -> str:
    return "".join(b.get("text", "") for b in result) if isinstance(result, list) else str(result)


def test_lists_only_read_tools(mcp_url):
    tools = asyncio.run(_tools(mcp_url))
    assert set(tools) == {"list_tickets", "get_ticket", "get_order", "get_delivery_events",
                          "get_refund_policy", "get_customer"}
    assert "tenant_id" not in str(tools["get_ticket"].args)


def test_calls_get_ticket_through_mcp(mcp_url):
    out = _text(_call(mcp_url, "get_ticket", {"ticket_number": "T-101"}))
    assert '"order_number": "O-101"' in out or '"order_number":"O-101"' in out


def test_tenant_comes_from_token_not_model(mcp_url):
    assert "not_found" in _text(_call(mcp_url, "get_ticket", {"ticket_number": "T-201"}))
    globex = _text(_call(mcp_url, "get_ticket", {"ticket_number": "T-201"}, tenant=GLOBEX))
    assert "O-201" in globex


@pytest.mark.parametrize("factory", [
    lambda t, r: "not-a-token",
    lambda t, r: run_token.mint(t, r, ttl_seconds=-30),
    lambda t, r: __import__("jwt").encode({"tenant_id": str(t), "run_id": str(r), "aud": "mcp-operations",
                                           "iss": "operations-worker", "iat": 0, "exp": 2**31},
                                          "wrong-secret-wrong-secret-0123456789", algorithm="HS256"),
])
def test_t28_t35_unauthenticated_or_invalid_tokens_are_denied(mcp_url, factory):
    with pytest.raises(BaseException):
        asyncio.run(_tools(mcp_url, token_factory=factory))


def test_raw_http_without_token_gets_401(mcp_url):
    r = httpx.post(mcp_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401


def test_agent_completes_one_ticket_investigation_via_mcp(client, graph, mcp_url):
    WorkflowDeps.tool_provider = MCPToolProvider(url=mcp_url)
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    assert run_detail(client, run_id)["status"] == "awaiting_approval"
    assert approvals_for(client, run_id)["refund"]["payload"]["amount_minor"] == 120000
    assert count("SELECT count(*) FROM agent_events WHERE run_id=:r AND event_type='tool_completed'", r=run_id) >= 4


def test_demo_model_works_over_mcp(client, graph, mcp_url):
    from app.agent.models import DemoHeuristicModel
    from tests.conftest import use_model

    WorkflowDeps.tool_provider = MCPToolProvider(url=mcp_url)
    use_model(lambda _: DemoHeuristicModel())
    run_id = start(client, "T-101")
    drain(graph)
    types = {a["action_type"] for a in run_detail(client, run_id)["actions"]}
    assert types == {"refund", "send_reply"}


def test_mcp_unavailable_fails_closed(client, graph):
    WorkflowDeps.tool_provider = MCPToolProvider(url=f"http://127.0.0.1:{_free_port()}/mcp")
    use_script(investigation_script("T-101", "O-101", [refund("O-101", 120000)]))
    run_id = start(client, "T-101")
    drain(graph)
    detail = run_detail(client, run_id)
    assert detail["status"] == "failed"
    assert detail["error_code"] == "tools_unavailable"
    assert detail["actions"] == []
