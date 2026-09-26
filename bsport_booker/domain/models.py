from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass


def plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c)).strip()


def same_class(a: str, b: str) -> bool:
    return plain(a) == plain(b)


@dataclass(frozen=True)
class Offer:
    id: int
    name: str
    start: dt.datetime
    available: bool
    full: bool
    credits: int


@dataclass(frozen=True)
class Pack:
    id: int
    start: dt.date
    end: dt.date
    credits: int | None  # None: bsport keeps no count, the pack is unlimited
    disabled: bool

    def covers(self, day: dt.date) -> bool:
        return not self.disabled and self.start <= day <= self.end


@dataclass(frozen=True)
class Wanted:
    name: str
    days: frozenset[int]
    time: dt.time

    def matches(self, name: str, start: dt.datetime) -> bool:
        # `start` carries the studio's own offset, so its wall clock is the studio's.
        return (
            same_class(name, self.name)
            and start.weekday() in self.days
            and (start.hour, start.minute) == (self.time.hour, self.time.minute)
        )


@dataclass(frozen=True)
class Listing:
    """A class in a studio's timetable, whoever it is for."""

    company: str
    activity: str
    start: dt.datetime
