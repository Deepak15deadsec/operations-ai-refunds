"""LangGraph PostgreSQL checkpointer lifecycle.

PostgresSaver needs psycopg3 connections with autocommit=True and dict_row. Tables live in the
`langgraph` schema via `search_path` in LANGGRAPH_DATABASE_URL. `setup()` runs once, from the
`migrate` service (see scripts/migrate.py), not on every worker start.
"""

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

CONNECTION_KWARGS = {"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}


def open_pool(url: str | None = None, max_size: int = 8) -> ConnectionPool:
    return ConnectionPool(
        conninfo=url or get_settings().langgraph_database_url,
        min_size=1,
        max_size=max_size,
        kwargs=CONNECTION_KWARGS,
        open=True,
    )


def make_checkpointer(pool: ConnectionPool) -> PostgresSaver:
    return PostgresSaver(pool)  # type: ignore[arg-type]


def setup_checkpointer(url: str | None = None) -> None:
    with PostgresSaver.from_conn_string(url or get_settings().langgraph_database_url) as saver:
        saver.setup()
