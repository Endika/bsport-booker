"""One pass: book every wanted class that is published, open and payable, and say what changed."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .client import BsportError, Offer, Pack
from .config import Config
from .config import same_class as _same_class

log = logging.getLogger(__name__)
WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
FORGET_AFTER_DAYS = 120


class Client(Protocol):
    def member_id(self) -> int: ...
    def booked_offers(self) -> set[int]: ...
    def packs(self, member: int) -> list[Pack]: ...
    def offers(
        self, company: int, establishment: int, first: dt.date, last: dt.date
    ) -> list[Offer]: ...
    def book(self, pack: Pack, offer: Offer) -> None: ...


# Keys that describe a condition: once it stops being true the key goes, so it can be said again.
CONDITIONS = ("unavailable:", "full:", "nocredits:", "error:", "empty:", "low:", "nopack:")


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)  # one per wanted class, for --status
    news: list[tuple[str, str]] = field(default_factory=list)  # (key, text) not yet announced
    seen: set[str] = field(default_factory=set)  # every condition key true right now
    credits: str = ""
    published_until: str = ""
    failed: bool = False


class StateError(Exception):
    pass


def load_state(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise StateError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise StateError("not a JSON object")
    return {str(k): str(v) for k, v in raw.items()}


def save_state(path: Path, state: dict[str, str]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as out:
        out.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
        out.flush()
        os.fsync(out.fileno())
    tmp.replace(path)


def commit(state: dict[str, str], report: Report, today: dt.date, *, announced: bool) -> None:
    """Fold a run into the state. News only counts as said once Slack took it."""
    stamp = today.isoformat()
    for key in [k for k in state if k.startswith(CONDITIONS) and k not in report.seen]:
        del state[key]
    for key in report.seen & state.keys():
        state[key] = stamp
    if announced:
        state.update({key: stamp for key, _ in report.news})
    cutoff = (today - dt.timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    for key in [k for k, seen in state.items() if seen < cutoff]:
        del state[key]


def when(start: dt.datetime) -> str:
    return f"{WEEKDAYS[start.weekday()]} {start:%d/%m %H:%M}"


def _pay_with(packs: list[Pack], offer: Offer) -> Pack | None:
    usable = [
        p
        for p in packs
        if p.covers(offer.start.date())
        and (p.credits is None or p.credits >= offer.credits)
        and (p.credits is None or p.credits > 0)
    ]
    # The one that runs out first, so a pack never expires with credits left over.
    return min(usable, key=lambda p: p.end, default=None)


def _count(pack: Pack) -> str:
    return "ilimitados" if pack.credits is None else str(pack.credits)


def _credit_lines(packs: list[Pack], today: dt.date) -> list[Pack]:
    return sorted((p for p in packs if not p.disabled and p.end >= today), key=lambda p: p.start)


def run(
    client: Client, config: Config, state: dict[str, str], *, now: dt.datetime, dry_run: bool
) -> Report:
    """Books what it can (unless `dry_run`); never touches `state`, see `commit`."""
    report = Report()
    today = now.date()
    member = client.member_id()
    packs = client.packs(member)
    booked = client.booked_offers()
    offers = client.offers(
        config.company,
        config.establishment,
        today,
        today + dt.timedelta(days=config.horizon_days),
    )
    # How far your classes are published, whatever the day or hour: other activities may run
    # much further ahead and say nothing about yours.
    yours = [o.start for o in offers if any(_same_class(o.name, w.name) for w in config.classes)]
    if yours:
        last = max(yours)
        report.published_until = f"{WEEKDAYS[last.weekday()]} {last:%d/%m}"

    def news(key: str, text: str) -> None:
        if not key.startswith("booked:"):
            report.seen.add(key)
        if key not in state:
            report.news.append((key, text))

    wanted = sorted(
        (
            o
            for o in offers
            if o.start > now and any(w.matches(o.name, o.start) for w in config.classes)
        ),
        key=lambda o: o.start,
    )
    for offer in wanted:
        label = f"{when(offer.start)} {offer.name.title()}"
        if offer.id in booked:
            report.lines.append(f"✅ {label}: reservada")
            continue
        if not offer.available:
            report.lines.append(f"⛔ {label}: no disponible")
            news(f"unavailable:{offer.id}", f"⛔ {label}: el estudio la tiene como no disponible")
            continue
        if offer.full:
            report.lines.append(f"🚫 {label}: llena, sigo intentándolo")
            news(f"full:{offer.id}", f"🚫 {label}: está llena; la cojo si se libera una plaza")
            continue
        pack = _pay_with(packs, offer)
        if pack is None:
            report.lines.append(f"⚠️ {label}: sin créditos para ese día")
            news(
                f"nocredits:{offer.id}",
                f"⚠️ {label}: no la puedo reservar, no te quedan créditos para ese día",
            )
            continue
        if dry_run:
            report.lines.append(f"➕ {label}: la reservaría (bono hasta {pack.end:%d/%m})")
            continue
        try:
            client.book(pack, offer)
        except BsportError as exc:
            log.error("booking %s failed: %s", offer.id, exc)
            report.failed = True
            report.lines.append(f"❌ {label}: error al reservar ({exc})")
            news(f"error:{offer.id}:{exc.status}", f"❌ {label}: no he podido reservarla ({exc})")
            continue
        if pack.credits is not None:
            spent = Pack(pack.id, pack.start, pack.end, pack.credits - offer.credits, pack.disabled)
            packs = [spent if p.id == pack.id else p for p in packs]
        booked.add(offer.id)
        report.lines.append(f"🎉 {label}: reservada ahora")
        news(f"booked:{offer.id}", f"🎉 {label}: reservada")

    live = _credit_lines(packs, today)
    report.credits = "Créditos: " + (
        ", ".join(f"{_count(p)} (bono {p.start:%d/%m}–{p.end:%d/%m})" for p in live)
        if live
        else "no tienes ningún bono en vigor"
    )
    for p in live:
        if p.credits is None:
            continue
        if p.credits == 0:
            news(f"empty:{p.id}", f"🪫 Bono {p.start:%d/%m}–{p.end:%d/%m} agotado")
        elif p.credits <= config.low_credits:
            news(
                f"low:{p.id}:{p.credits}",
                f"🔋 Quedan {p.credits} créditos en el bono {p.start:%d/%m}–{p.end:%d/%m}",
            )
    if not live:
        news("nopack:", "🪫 No tienes ningún bono en vigor")
    return report
