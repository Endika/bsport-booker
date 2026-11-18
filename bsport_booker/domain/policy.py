"""Which wanted classes to book, and with which pack. Pure functions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto

from .models import Offer, Pack, Wanted, same_class

_SYNTHETIC = -1


class Reason(Enum):
    BOOKED = auto()
    CANCELLED = auto()
    UNAVAILABLE = auto()
    FULL = auto()
    NO_CREDITS = auto()


@dataclass(frozen=True)
class Skip:
    offer: Offer
    reason: Reason


@dataclass(frozen=True)
class Book:
    offer: Offer
    pack: Pack


Decision = Book | Skip


def due(offers: Iterable[Offer], wanted: Collection[Wanted], now: dt.datetime) -> list[Offer]:
    """The wanted classes that have not started yet, soonest first."""
    hits = (o for o in offers if o.start > now and any(w.matches(o.name, o.start) for w in wanted))
    return sorted(hits, key=lambda o: o.start)


def decide(
    offer: Offer,
    packs: Iterable[Pack],
    booked: Collection[int],
    cancelled: Collection[int] = (),
) -> Decision:
    if offer.id in booked:
        return Skip(offer, Reason.BOOKED)
    if offer.id in cancelled:
        return Skip(offer, Reason.CANCELLED)
    if not offer.available:
        return Skip(offer, Reason.UNAVAILABLE)
    if offer.full:
        return Skip(offer, Reason.FULL)
    pack = pay_with(packs, offer)
    if pack is None:
        return Skip(offer, Reason.NO_CREDITS)
    return Book(offer, pack)


def pay_with(packs: Iterable[Pack], offer: Offer) -> Pack | None:
    usable = [p for p in packs if p.covers(offer.start.date()) and _affords(p, offer)]
    # The one that runs out first, so a pack never expires with credits left over.
    return min(usable, key=lambda p: p.end, default=None)


def _affords(pack: Pack, offer: Offer) -> bool:
    return pack.credits is None or (pack.credits >= offer.credits and pack.credits > 0)


def spend(packs: Sequence[Pack], booking: Book) -> list[Pack]:
    """The packs once `booking` went through, so the next class in the run sees what is left."""
    pack = booking.pack
    if pack.credits is None:
        return list(packs)
    spent = replace(pack, credits=pack.credits - booking.offer.credits)
    return [spent if p.id == pack.id else p for p in packs]


def in_force(packs: Iterable[Pack], today: dt.date) -> list[Pack]:
    return sorted((p for p in packs if not p.disabled and p.end >= today), key=lambda p: p.start)


def published_until(offers: Iterable[Offer], wanted: Collection[Wanted]) -> dt.datetime | None:
    # Any day or hour counts: other activities may run much further ahead and say nothing
    # about yours.
    yours = [o.start for o in offers if any(same_class(o.name, w.name) for w in wanted)]
    return max(yours, default=None)


def unused_at_expiry(
    packs: Sequence[Pack],
    wanted: Collection[Wanted],
    offers: Iterable[Offer],
    booked: Collection[int],
    cancelled: Collection[int],
    now: dt.datetime,
    published_until: dt.datetime | None,
) -> list[tuple[Pack, int]]:
    """The packs that will still hold credits when they expire, if you keep booking at your pace.

    A day inside the published range with no class (the studio is closed) is not counted.
    """
    slots = [o for o in due(offers, wanted, now) if o.id not in booked and o.id not in cancelled]
    slots += _projected(wanted, packs, now, published_until)
    left = list(packs)
    for slot in slots:
        pack = pay_with(left, slot)
        if pack is not None:
            left = spend(left, Book(slot, pack))
    return [
        (p, p.credits)
        for p in in_force(left, now.date())
        if p.credits is not None and p.credits > 0
    ]


def _projected(
    wanted: Collection[Wanted],
    packs: Iterable[Pack],
    now: dt.datetime,
    published_until: dt.datetime | None,
) -> list[Offer]:
    first = now.date() if published_until is None else published_until.date() + dt.timedelta(days=1)
    last = max((p.end for p in packs if not p.disabled), default=first)
    days = (first + dt.timedelta(days=n) for n in range((last - first).days + 1))
    slots = (
        Offer(_SYNTHETIC, w.name, dt.datetime.combine(day, w.time, now.tzinfo), True, False, 1)
        for day in days
        for w in wanted
        if day.weekday() in w.days
    )
    return sorted((o for o in slots if o.start > now), key=lambda o: o.start)
