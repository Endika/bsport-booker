"""What the state keeps between runs, and when it lets go."""

from __future__ import annotations

import datetime as dt

from .booking import Report

FORGET_AFTER_DAYS = 120
# Keys that describe a condition: once it stops being true the key goes, so it can be said again.
CONDITIONS = ("unavailable:", "full:", "nocredits:", "error:", "empty:", "low:", "nopack:")


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
