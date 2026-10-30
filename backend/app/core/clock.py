"""Single source of "now" so tests can pin time deterministically."""

from collections.abc import Callable
from datetime import UTC, datetime

_now: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def now_utc() -> datetime:
    return _now()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Override the clock (tests only). Pass None to restore the real clock."""
    global _now
    _now = fn or (lambda: datetime.now(UTC))
