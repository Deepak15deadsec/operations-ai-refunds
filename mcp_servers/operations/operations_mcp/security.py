"""Authentication for the MCP operations server.

Callers present a short-lived run token minted by the worker (see app.core.run_token). The tenant
is taken from the verified token and injected server-side; no tool accepts a tenant argument.
"""

import logging
import uuid

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from app.core import run_token

log = logging.getLogger(__name__)


class RunTokenVerifier:
    """Implements the MCP SDK `TokenVerifier` protocol."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            scope, claims = run_token.verify(token)
        except jwt.PyJWTError as exc:
            log.warning("rejected MCP token: %s", type(exc).__name__)
            return None
        return AccessToken(
            token=token,
            client_id="operations-worker",
            scopes=["operations:read"],
            expires_at=int(claims["exp"]),
            subject=f"run:{scope.run_id}",
            claims=claims,
        )


class ScopeError(PermissionError):
    pass


def current_scope() -> run_token.RunScope:
    """Tenant/run of the authenticated caller for the current MCP request."""
    token = get_access_token()
    if token is None or not token.claims:
        raise ScopeError("unauthenticated MCP request")
    return run_token.RunScope(uuid.UUID(token.claims["tenant_id"]), uuid.UUID(token.claims["run_id"]))
