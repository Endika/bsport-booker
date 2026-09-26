"""Which wanted classes to book, and with which pack. Pure functions."""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto

from .models import Offer, Pack, Wanted, same_class


class Reason(Enum):
    BOOKED = auto()
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


def decide(offer: Offer, packs: Iterable[Pack], booked: Collection[int]) -> Decision:
    if offer.id in booked:
        return Skip(offer, Reason.BOOKED)
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
