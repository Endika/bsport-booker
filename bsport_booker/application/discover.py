"""`--discover`: the studios bsport admits are yours, their ids, and what they teach when."""

from __future__ import annotations

import datetime as dt

from ..ports import BookingGateway, BsportError
from . import messages

LOOKAHEAD = dt.timedelta(days=14)


def discover(bsport: BookingGateway, today: dt.date) -> bool:
    try:
        bsport.login()
        studios = bsport.studios()
        if not studios:
            print(messages.NO_STUDIOS)
            return False
        for establishment, title in sorted(studios.items()):
            listings = bsport.timetable(establishment, today, today + LOOKAHEAD)
            print(messages.studio(title, establishment, listings))
    except (BsportError, KeyError, ValueError) as exc:
        print(messages.discover_failed(exc))
        return False
    return True
