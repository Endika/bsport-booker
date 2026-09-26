"""One pass over the wanted classes: book what can be booked, and note what is worth saying."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from ..config import Config
from ..domain.models import Pack
from ..domain.policy import Book, Skip, decide, due, in_force, published_until, spend
from ..ports import BookingGateway, BsportError
from . import messages
from .memory import Topic

log = logging.getLogger(__name__)


@dataclass
class Report:
    said: Collection[str]  # keys announced by earlier runs
    lines: list[str] = field(default_factory=list)  # one per wanted class, for --status
    news: list[tuple[str, str]] = field(default_factory=list)  # (key, text) not yet announced
    seen: set[str] = field(default_factory=set)  # every condition key true right now
    credits: str = ""
    published_until: dt.datetime | None = None
    failed: bool = False

    def note(self, topic: Topic, *parts: object, text: str) -> None:
        key = topic.key(*parts)
        if topic.is_condition:
            self.seen.add(key)
        if key not in self.said:
            self.news.append((key, text))


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
    fetched = packs = bsport.packs(member)
    booked = bsport.booked_offers()
    last = today + dt.timedelta(days=config.horizon_days)
    offers = bsport.offers(config.company, config.establishment, today, last)
    report.published_until = published_until(offers, config.classes)
    for offer in due(offers, config.classes, now):
        decision = decide(offer, packs, booked)
        if isinstance(decision, Skip):
            _skip(report, decision)
            continue
        if dry_run:
            report.lines.append(messages.would_book_line(decision))
        elif not _book(bsport, report, decision):
            continue
        packs = spend(packs, decision)
        booked.add(offer.id)
    # A look spends nothing for real, so its balance is the one bsport has.
    _credits(report, fetched if dry_run else packs, today, config.low_credits)
    return report


def _skip(report: Report, skip: Skip) -> None:
    report.lines.append(messages.skip_line(skip))
    topic = Topic[skip.reason.name]
    if topic.is_condition:
        report.note(topic, skip.offer.id, text=messages.skip_news(skip))


def _book(bsport: BookingGateway, report: Report, booking: Book) -> bool:
    offer = booking.offer
    try:
        bsport.book(booking.pack, offer)
    except BsportError as exc:
        log.error("booking %s failed: %s", offer.id, exc)
        report.failed = True
        report.lines.append(messages.failed_line(offer, exc))
        report.note(Topic.ERROR, offer.id, exc.status, text=messages.failed_news(offer, exc))
        return False
    report.lines.append(messages.booked_line(offer))
    report.note(Topic.BOOKED, offer.id, text=messages.booked_news(offer))
    return True


def _credits(report: Report, packs: Sequence[Pack], today: dt.date, low: int) -> None:
    live = in_force(packs, today)
    report.credits = messages.credits(live)
    for pack in live:
        if pack.credits == 0:
            report.note(Topic.EMPTY, pack.id, text=messages.empty(pack))
        elif pack.credits is not None and pack.credits <= low:
            report.note(Topic.LOW, pack.id, pack.credits, text=messages.low(pack))
    if not live:
        report.note(Topic.NO_PACK, text=messages.NO_PACK)
