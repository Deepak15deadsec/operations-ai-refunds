"""Application settings loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Databases
    database_url: str = "postgresql+psycopg://app:local_only@localhost:5432/operations"
    mcp_database_url: str | None = None
    langgraph_database_url: str = (
        "postgresql://app:local_only@localhost:5432/operations?options=-csearch_path%3Dlanggraph"
    )

    # OIDC. The issuer is the public (browser-facing) URL and must equal the token `iss`;
    # signing keys are fetched from the internal JWKS URL.
    oidc_issuer_url: str = "http://localhost:8080/realms/operations-demo"
    oidc_jwks_url: str = "http://keycloak:8080/realms/operations-demo/protocol/openid-connect/certs"
    oidc_audience: str = "operations-api"
    oidc_tenant_claim: str = "tenant_id"

    # Agent
    agent_model: str = "openai:gpt-4.1-mini"
    agent_tool_transport: Literal["mcp", "direct"] = "mcp"
    agent_timeout_seconds: float = 120.0
    agent_max_tool_calls: int = 15
    agent_max_model_calls: int = 12
    tool_timeout_seconds: float = 10.0

    # MCP
    mcp_internal_url: str = "http://mcp-operations:3001/mcp"
    mcp_run_token_secret: str = Field(default="local-development-only-change-me", min_length=16)
    mcp_run_token_ttl_seconds: int = 900
    mcp_allowed_hosts: str = "mcp-operations:3001,localhost:3001,127.0.0.1:3001"

    # Limits and behaviour
    log_level: str = "INFO"
    max_batch_tickets: int = 10
    max_concurrent_ticket_runs: int = 2
    approval_ttl_hours: int = 24
    worker_lease_seconds: int = 300
    worker_poll_seconds: float = 1.0
    worker_sweep_seconds: float = 60.0
    job_max_attempts: int = 3
    cors_origins: str = "http://localhost:3000"
    runs_per_minute_per_user: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
