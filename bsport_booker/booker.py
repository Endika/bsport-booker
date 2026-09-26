"""One pass: book every wanted class that is published, open and payable, and say what changed."""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .client import BsportError, Offer, Pack
from .config import Config

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


@dataclass
class Report:
    lines: list[str] = field(default_factory=list)  # one per wanted class, for --status
    news: list[str] = field(default_factory=list)  # first time seen: what goes to Slack
    credits: str = ""
    published_until: str = ""
    failed: bool = False


def load_state(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def save_state(path: Path, state: dict[str, str]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def when(start: dt.datetime) -> str:
    return f"{WEEKDAYS[start.weekday()]} {start:%d/%m %H:%M}"


def _pay_with(packs: list[Pack], offer: Offer) -> Pack | None:
    need = max(offer.credits, 1)
    usable = [p for p in packs if p.covers(offer.start.date()) and p.credits >= need]
    # The one that runs out first, so a pack never expires with credits left over.
    return min(usable, key=lambda p: p.end, default=None)


def _credit_lines(packs: list[Pack], today: dt.date) -> list[Pack]:
    return sorted((p for p in packs if not p.disabled and p.end >= today), key=lambda p: p.start)


def run(
    client: Client, config: Config, state: dict[str, str], *, now: dt.datetime, dry_run: bool
) -> Report:
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
    if offers:
        last = max(o.start for o in offers)
        report.published_until = f"{WEEKDAYS[last.weekday()]} {last:%d/%m}"

    def news(key: str, text: str) -> None:
        if key not in state:
            report.news.append(text)
            if not dry_run:
                state[key] = today.isoformat()

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
        packs = [
            Pack(p.id, p.start, p.end, p.credits - max(offer.credits, 1), p.disabled)
            if p.id == pack.id
            else p
            for p in packs
        ]
        booked.add(offer.id)
        report.lines.append(f"🎉 {label}: reservada ahora")
        news(f"booked:{offer.id}", f"🎉 {label}: reservada")

    live = _credit_lines(packs, today)
    report.credits = "Créditos: " + (
        ", ".join(f"{p.credits} (bono {p.start:%d/%m}–{p.end:%d/%m})" for p in live)
        if live
        else "no tienes ningún bono en vigor"
    )
    for p in live:
        if p.credits == 0:
            news(f"empty:{p.id}", f"🪫 Bono {p.start:%d/%m}–{p.end:%d/%m} agotado")
        elif p.credits <= config.low_credits:
            news(
                f"low:{p.id}:{p.credits}",
                f"🔋 Quedan {p.credits} créditos en el bono {p.start:%d/%m}–{p.end:%d/%m}",
            )
    if not live:
        news(f"nopack:{today:%Y-%m}", "🪫 No tienes ningún bono en vigor")

    cutoff = (today - dt.timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    for key in [k for k, seen in state.items() if seen < cutoff]:
        del state[key]
    return report
