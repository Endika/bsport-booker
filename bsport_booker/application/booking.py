"""One pass over the wanted classes: book what can be booked, and note what is worth saying."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from enum import Enum

from ..config import Config
from ..domain import Book, Pack, Reason, Skip, decide, due, in_force, published_until, spend
from ..ports import BookingGateway, BsportError
from . import messages

log = logging.getLogger(__name__)


class Condition(Enum):
    """Something true right now: once it stops being true its key goes, so it can be said again."""

    UNAVAILABLE = "unavailable"
    FULL = "full"
    NO_CREDITS = "nocredits"
    ERROR = "error"
    EMPTY = "empty"
    LOW = "low"
    NO_PACK = "nopack"

    @property
    def prefix(self) -> str:
        return f"{self.value}:"

    def key(self, *parts: object) -> str:
        return self.prefix + ":".join(map(str, parts))


SKIP_CONDITIONS = {
    Reason.UNAVAILABLE: Condition.UNAVAILABLE,
    Reason.FULL: Condition.FULL,
    Reason.NO_CREDITS: Condition.NO_CREDITS,
}


@dataclass
class Report:
    said: Collection[str]  # keys announced by earlier runs
    lines: list[str] = field(default_factory=list)  # one per wanted class, for --status
    news: list[tuple[str, str]] = field(default_factory=list)  # (key, text) not yet announced
    seen: set[str] = field(default_factory=set)  # every condition key true right now
    credits: str = ""
    published_until: dt.datetime | None = None
    failed: bool = False

    def announce(self, key: str, text: str) -> None:
        if key not in self.said:
            self.news.append((key, text))

    def condition(self, key: str, text: str) -> None:
        self.seen.add(key)
        self.announce(key, text)


def book_due(
    bsport: BookingGateway,
    config: Config,
    state: Collection[str],
    *,
    now: dt.datetime,
    dry_run: bool,
) -> Report:
    """Books what it can (unless `dry_run`); leaves `state` alone, see `memory.remember`."""
    report = Report(said=state)
    today = now.date()
    member = bsport.member_id()
    packs = bsport.packs(member)
    booked = bsport.booked_offers()
    last = today + dt.timedelta(days=config.horizon_days)
    offers = bsport.offers(config.company, config.establishment, today, last)
    report.published_until = published_until(offers, config.classes)
    for offer in due(offers, config.classes, now):
        decision = decide(offer, packs, booked)
        if isinstance(decision, Skip):
            _skip(report, decision)
        elif dry_run:
            report.lines.append(messages.would_book_line(decision))
        elif _book(bsport, report, decision):
            packs = spend(packs, decision)
            booked.add(offer.id)
    _credits(report, packs, today, config.low_credits)
    return report


def _skip(report: Report, skip: Skip) -> None:
    report.lines.append(messages.skip_line(skip))
    condition = SKIP_CONDITIONS.get(skip.reason)
    if condition:
        report.condition(condition.key(skip.offer.id), messages.skip_news(skip))


def _book(bsport: BookingGateway, report: Report, booking: Book) -> bool:
    offer = booking.offer
    try:
        bsport.book(booking.pack, offer)
    except BsportError as exc:
        log.error("booking %s failed: %s", offer.id, exc)
        report.failed = True
        report.lines.append(messages.failed_line(offer, exc))
        report.condition(
            Condition.ERROR.key(offer.id, exc.status), messages.failed_news(offer, exc)
        )
        return False
    report.lines.append(messages.booked_line(offer))
    report.announce(f"booked:{offer.id}", messages.booked_news(offer))
    return True


def _credits(report: Report, packs: Sequence[Pack], today: dt.date, low: int) -> None:
    live = in_force(packs, today)
    report.credits = messages.credits(live)
    for pack in live:
        if pack.credits == 0:
            report.condition(Condition.EMPTY.key(pack.id), messages.empty(pack))
        elif pack.credits is not None and pack.credits <= low:
            report.condition(Condition.LOW.key(pack.id, pack.credits), messages.low(pack))
    if not live:
        report.condition(Condition.NO_PACK.key(), messages.NO_PACK)
