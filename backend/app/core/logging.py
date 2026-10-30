"""Structured JSON logging with correlation fields."""

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.errors import request_id_var

_CONTEXT_FIELDS = ("run_id", "thread_id", "action_id", "tenant_id", "job_id")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for field in _CONTEXT_FIELDS:
            if hasattr(record, field):
                entry[field] = str(getattr(record, field))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "mcp", "fastmcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
