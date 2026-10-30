import hashlib
import json
import uuid
from typing import Any


def action_fingerprint(
    *, action_type: str, ticket_id: uuid.UUID, payload: dict[str, Any], policy_version: str | None
) -> str:
    """SHA-256 over the canonical JSON of everything that defines an action."""
    canonical = json.dumps(
        {
            "action_type": action_type,
            "ticket_id": str(ticket_id),
            "payload": payload,
            "policy_version": policy_version,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
