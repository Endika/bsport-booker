"""The boundaries the application talks to. Everything that knows about HTTP, Slack or
files lives behind them, in `adapters/`.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from .domain.models import Listing, Offer, Pack


class BsportError(Exception):
    def __init__(self, what: str, status: int, detail: str = "") -> None:
        super().__init__(f"{what}: HTTP {status} {detail}".rstrip())
        self.status = status


class BookingGateway(Protocol):
    def login(self, email: str, password: str) -> None: ...
    def member_id(self) -> int: ...
    def booked_offers(self) -> set[int]: ...
    def packs(self, member: int) -> list[Pack]: ...
    def offers(
        self, company: int, establishment: int, first: dt.date, last: dt.date
    ) -> list[Offer]: ...
    def book(self, pack: Pack, offer: Offer) -> None: ...

    def studios(self) -> dict[int, str]:
        """Where your upcoming bookings are: the only way bsport tells a member its studios."""
        ...

    def timetable(self, establishment: int, first: dt.date, last: dt.date) -> list[Listing]: ...


class Notifier(Protocol):
    def send(self, text: str) -> bool:
        """Deliver `text`. Returns whether it actually got through."""
        ...


class StateError(Exception):
    pass


class StateStore(Protocol):
    def load(self) -> dict[str, str]:
        """Empty when there is nothing yet; raises `StateError` when it cannot be read."""
        ...

    def set_aside(self, now: dt.datetime) -> str | None:
        """Move an unreadable state out of the way. Returns where to, or None if it can't."""
        ...

    def save(self, state: dict[str, str]) -> bool: ...
