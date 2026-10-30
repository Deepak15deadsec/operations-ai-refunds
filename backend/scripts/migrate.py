"""One-shot setup used by the `migrate` Compose service:
alembic upgrade head -> LangGraph checkpointer setup() -> seed demo data (unless SEED_DEMO=false)."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.workflow.checkpoint import setup_checkpointer

BACKEND = Path(__file__).resolve().parents[1]


def main() -> None:
    command.upgrade(Config(str(BACKEND / "alembic.ini")), "head")
    print("migrations: at head")
    setup_checkpointer()
    print("checkpointer: ready")
    if os.environ.get("SEED_DEMO", "true").lower() == "true":
        from scripts.seed import main as seed_main

        seed_main()


if __name__ == "__main__":
    main()
