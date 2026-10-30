import time
from collections import defaultdict, deque

from app.core.auth import Principal
from app.core.config import get_settings
from app.core.errors import AppError

_recent: dict[str, deque[float]] = defaultdict(deque)


def enforce_run_rate_limit(principal: Principal) -> None:
    """Simple in-process sliding window. Good enough for one API replica in local Compose."""
    limit = get_settings().runs_per_minute_per_user
    now = time.monotonic()
    window = _recent[principal.user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= limit:
        raise AppError(429, "rate_limited", "Too many runs started; try again in a minute")
    window.append(now)
