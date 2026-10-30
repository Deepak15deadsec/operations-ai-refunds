"""Short-lived, run-scoped tokens the worker presents to the MCP server.

The token carries the tenant and run so the MCP server scopes every read without ever accepting a
tenant chosen by the model.
"""

import time
import uuid
from dataclasses import dataclass

import jwt

from app.core.config import get_settings

AUDIENCE = "mcp-operations"
ISSUER = "operations-worker"


@dataclass(frozen=True)
class RunScope:
    tenant_id: uuid.UUID
    run_id: uuid.UUID


def mint(tenant_id: uuid.UUID, run_id: uuid.UUID, ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": f"run:{run_id}",
        "tenant_id": str(tenant_id),
        "run_id": str(run_id),
        "iat": now,
        "exp": now + (ttl_seconds or settings.mcp_run_token_ttl_seconds),
    }
    return jwt.encode(claims, settings.mcp_run_token_secret, algorithm="HS256")


def verify(token: str) -> tuple[RunScope, dict]:
    """Raises jwt.PyJWTError on any problem (bad signature, audience, issuer or expiry)."""
    claims = jwt.decode(
        token,
        get_settings().mcp_run_token_secret,
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "tenant_id", "run_id"]},
    )
    return RunScope(uuid.UUID(claims["tenant_id"]), uuid.UUID(claims["run_id"])), claims
