"""What the state keeps between runs, and when it lets go."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .booking import Report

FORGET_AFTER_DAYS = 120


class Topic(Enum):
    """What a state key is about. The names of the skip reasons match `domain.Reason`."""

    BOOKED = "booked"
    FATAL = "fatal"
    UNAVAILABLE = "unavailable"
    FULL = "full"
    NO_CREDITS = "nocredits"
    ERROR = "error"
    EMPTY = "empty"
    LOW = "low"
    NO_PACK = "nopack"

    @property
    def is_condition(self) -> bool:
        """True right now, and forgotten once it stops being, so it can be said again."""
        return self not in (Topic.BOOKED, Topic.FATAL)

    def key(self, *parts: object) -> str:
        return f"{self.value}:" + ":".join(map(str, parts))


CONDITIONS = tuple(f"{t.value}:" for t in Topic if t.is_condition)


def remember(
    state: dict[str, str], report: Report, today: dt.date, *, announced: bool
) -> dict[str, str]:
    """Fold a run into the state. News only counts as said once Slack took it."""
    stamp = today.isoformat()
    kept = {k: v for k, v in state.items() if not k.startswith(CONDITIONS) or k in report.seen}
    kept.update(dict.fromkeys(report.seen & kept.keys(), stamp))
    if announced:
        kept.update({key: stamp for key, _ in report.news})
    cutoff = (today - dt.timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    return {k: seen for k, seen in kept.items() if seen >= cutoff}
