"""One pass: book every wanted class that is published, open and payable, and say what changed."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from . import domain
from .config import Config
from .domain import Pack
from .ports import BookingGateway, BsportError

log = logging.getLogger(__name__)
WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
FORGET_AFTER_DAYS = 120


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


def _count(pack: Pack) -> str:
    return "ilimitados" if pack.credits is None else str(pack.credits)


def run(
    client: BookingGateway,
    config: Config,
    state: dict[str, str],
    *,
    now: dt.datetime,
    dry_run: bool,
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
    last = domain.published_until(offers, config.classes)
    if last:
        report.published_until = f"{WEEKDAYS[last.weekday()]} {last:%d/%m}"

    def news(key: str, text: str) -> None:
        if not key.startswith("booked:"):
            report.seen.add(key)
        if key not in state:
            report.news.append((key, text))

    for offer in domain.due(offers, config.classes, now):
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
        pack = domain.pay_with(packs, offer)
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
        packs = domain.spend(packs, domain.Book(offer, pack))
        booked.add(offer.id)
        report.lines.append(f"🎉 {label}: reservada ahora")
        news(f"booked:{offer.id}", f"🎉 {label}: reservada")

    live = domain.in_force(packs, today)
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
