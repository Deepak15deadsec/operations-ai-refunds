"""Read-only tool providers for the investigation agent.

`DirectToolProvider` wraps the read services in-process (unit tests, local fallback).
`MCPToolProvider` loads the same tools from the MCP operations server via `langchain.mcp.MCPAdapter`.
Both are scoped to one tenant/run; the model never supplies a tenant.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from langchain_core.tools import BaseTool, StructuredTool

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import transaction
from app.services import read_service

READ_TOOL_NAMES = (
    "list_tickets",
    "get_ticket",
    "get_order",
    "get_delivery_events",
    "get_refund_policy",
    "get_customer",
)


class ToolProvider(Protocol):
    def tools(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> Any:
        """Async context manager yielding a list of LangChain tools."""
        ...


def safe_call(fn: Callable[..., dict], *args: Any, **kwargs: Any) -> dict:
    """Return domain errors as data so the model can report them instead of crashing the run."""
    try:
        return fn(*args, **kwargs)
    except AppError as exc:
        return {"error": exc.error_code, "message": exc.message}


def build_read_functions(tenant_id: uuid.UUID, db_url: str | None = None) -> dict[str, Callable[..., dict]]:
    """Plain functions with the tenant bound. Shared by direct tools and the MCP server."""

    def run(fn, *args, **kwargs) -> dict:
        with transaction(db_url) as session:
            return safe_call(fn, session, tenant_id, *args, **kwargs)

    def list_tickets(status: str | None = None, priority: str | None = None, limit: int = 20,
                     cursor: str | None = None) -> dict:
        """List support tickets (max 20 per page), optionally filtered by status and priority."""
        return run(read_service.list_tickets, status=status, priority=priority, limit=limit, cursor=cursor)

    def get_ticket(ticket_number: str) -> dict:
        """Get one support ticket by number (e.g. T-101), including its linked order number."""
        return run(read_service.get_ticket, ticket_number)

    def get_order(order_number: str) -> dict:
        """Get an order by number (e.g. O-101): payment, total, shipping status and dates."""
        return run(read_service.get_order, order_number)

    def get_delivery_events(order_number: str) -> dict:
        """Get the delivery event history for an order, oldest first."""
        return run(read_service.get_delivery_events, order_number)

    def get_refund_policy(version: str | None = None) -> dict:
        """Get the active refund policy (or a specific version): thresholds and policy text."""
        return run(read_service.get_refund_policy, version)

    def get_customer(customer_ref: str) -> dict:
        """Get minimal customer details (name, masked email) by customer reference."""
        return run(read_service.get_customer, customer_ref)

    return {
        "list_tickets": list_tickets,
        "get_ticket": get_ticket,
        "get_order": get_order,
        "get_delivery_events": get_delivery_events,
        "get_refund_policy": get_refund_policy,
        "get_customer": get_customer,
    }


class DirectToolProvider:
    @asynccontextmanager
    async def tools(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> AsyncIterator[list[BaseTool]]:
        fns = build_read_functions(tenant_id)
        yield [StructuredTool.from_function(fn, name=name) for name, fn in fns.items()]


class MCPToolProvider:
    """Isolates the beta `langchain.mcp` API behind the ToolProvider interface."""

    def __init__(self, url: str | None = None, token_factory: Callable[[uuid.UUID, uuid.UUID], str] | None = None):
        settings = get_settings()
        self.url = url or settings.mcp_internal_url
        self.timeout = settings.tool_timeout_seconds
        if token_factory is None:
            from app.core.run_token import mint

            token_factory = mint
        self.token_factory = token_factory

    @asynccontextmanager
    async def tools(self, tenant_id: uuid.UUID, run_id: uuid.UUID) -> AsyncIterator[list[BaseTool]]:
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        from langchain.mcp import MCPAdapter

        token = self.token_factory(tenant_id, run_id)
        transport = StreamableHttpTransport(self.url, headers={"Authorization": f"Bearer {token}"})
        adapter = MCPAdapter(Client(transport, timeout=self.timeout, init_timeout=self.timeout))
        async with adapter:
            tools = await adapter.list_tools()
            allowed = [t for t in tools if t.name in READ_TOOL_NAMES]  # allowlist, even if server adds more
            yield allowed


def default_tool_provider() -> ToolProvider:
    return MCPToolProvider() if get_settings().agent_tool_transport == "mcp" else DirectToolProvider()
