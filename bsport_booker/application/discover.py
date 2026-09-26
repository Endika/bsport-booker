"""`--discover`: the studios bsport admits are yours, their ids, and what they teach when."""

from __future__ import annotations

import datetime as dt

from ..ports import BookingGateway, BsportError
from . import messages

LOOKAHEAD = dt.timedelta(days=14)


def discover(bsport: BookingGateway, today: dt.date) -> tuple[bool, list[str]]:
    """Whether it worked, and what to show."""
    found: list[str] = []
    try:
        bsport.login()
        studios = bsport.studios()
        if not studios:
            return False, [messages.NO_STUDIOS]
        for establishment, title in sorted(studios.items()):
            listings = bsport.timetable(establishment, today, today + LOOKAHEAD)
            found.append(messages.studio(title, establishment, listings))
    except (BsportError, KeyError, ValueError) as exc:
        return False, [*found, messages.discover_failed(exc)]
    return True, found
