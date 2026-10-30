"""Bearer-token authentication and role-based authorization.

Tenant and roles come only from a verified access token, never from request bodies.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import jwt
from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.errors import AppError, forbidden

ROLE_RANK = {"operator": 1, "supervisor": 2, "admin": 3}


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: uuid.UUID
    roles: frozenset[str]
    username: str | None = None

    def has_role(self, minimum: str) -> bool:
        need = ROLE_RANK[minimum]
        return any(ROLE_RANK.get(r, 0) >= need for r in self.roles)


class KeyResolver(Protocol):
    def signing_key(self, token: str) -> object: ...


class JwksKeyResolver:
    def __init__(self, jwks_url: str):
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    def signing_key(self, token: str) -> object:
        return self._client.get_signing_key_from_jwt(token).key


class StaticKeyResolver:
    """Used by tests: verifies tokens signed by a locally generated key pair."""

    def __init__(self, public_key: object):
        self._key = public_key

    def signing_key(self, token: str) -> object:
        return self._key


_resolver_override: KeyResolver | None = None


def set_key_resolver(resolver: KeyResolver | None) -> None:
    global _resolver_override
    _resolver_override = resolver


@lru_cache
def _default_resolver() -> KeyResolver:
    return JwksKeyResolver(get_settings().oidc_jwks_url)


def _resolver() -> KeyResolver:
    return _resolver_override or _default_resolver()


def unauthenticated(message: str = "Missing or invalid access token") -> AppError:
    return AppError(401, "unauthenticated", message)


def verify_access_token(token: str) -> Principal:
    settings = get_settings()
    try:
        key = _resolver().signing_key(token)
        claims = jwt.decode(
            token,
            key=key,  # type: ignore[arg-type]
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer_url,
            options={"require": ["exp", "iat", "iss", "sub"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise unauthenticated() from exc

    raw_tenant = claims.get(settings.oidc_tenant_claim)
    if not raw_tenant:
        raise forbidden("Token has no tenant assignment")
    try:
        tenant_id = uuid.UUID(str(raw_tenant))
    except ValueError as exc:
        raise forbidden("Token has an invalid tenant assignment") from exc

    roles = frozenset(r for r in claims.get("realm_access", {}).get("roles", []) if r in ROLE_RANK)
    if not roles:
        raise forbidden("Token has no application role")
    return Principal(
        user_id=str(claims["sub"]),
        tenant_id=tenant_id,
        roles=roles,
        username=claims.get("preferred_username"),
    )


def get_principal(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthenticated()
    return verify_access_token(token.strip())


def require_role(minimum: str) -> Callable[[Principal], Principal]:
    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has_role(minimum):
            raise forbidden(f"Requires the {minimum} role")
        return principal

    return dependency


require_operator = require_role("operator")
require_supervisor = require_role("supervisor")
require_admin = require_role("admin")
