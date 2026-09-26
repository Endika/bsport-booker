"""Every word a person reads: the Slack news, the `--status` picture and `--discover`."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from pathlib import Path

from ..domain import Book, Listing, Offer, Pack, Reason, Skip

WEEKDAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
DRY_RUN = "(simulado, no se ha reservado nada)\n"
NOTHING_PUBLISHED = "No hay ninguna de tus clases publicada todavía."
NO_PACK = "🪫 No tienes ningún bono en vigor"
NO_STUDIOS = "No upcoming bookings, so bsport won't say which studios are yours. Book one."

_SKIP_LINES = {
    Reason.BOOKED: "✅ {}: reservada",
    Reason.UNAVAILABLE: "⛔ {}: no disponible",
    Reason.FULL: "🚫 {}: llena, sigo intentándolo",
    Reason.NO_CREDITS: "⚠️ {}: sin créditos para ese día",
}
_SKIP_NEWS = {
    Reason.UNAVAILABLE: "⛔ {}: el estudio la tiene como no disponible",
    Reason.FULL: "🚫 {}: está llena; la cojo si se libera una plaza",
    Reason.NO_CREDITS: "⚠️ {}: no la puedo reservar, no te quedan créditos para ese día",
}


def when(start: dt.datetime) -> str:
    return f"{WEEKDAYS[start.weekday()]} {start:%d/%m %H:%M}"


def _label(offer: Offer) -> str:
    return f"{when(offer.start)} {offer.name.title()}"


def _span(pack: Pack) -> str:
    return f"{pack.start:%d/%m}–{pack.end:%d/%m}"


def _count(pack: Pack) -> str:
    return "ilimitados" if pack.credits is None else str(pack.credits)


def skip_line(skip: Skip) -> str:
    return _SKIP_LINES[skip.reason].format(_label(skip.offer))


def skip_news(skip: Skip) -> str:
    return _SKIP_NEWS[skip.reason].format(_label(skip.offer))


def would_book_line(booking: Book) -> str:
    return f"➕ {_label(booking.offer)}: la reservaría (bono hasta {booking.pack.end:%d/%m})"


def booked_line(offer: Offer) -> str:
    return f"🎉 {_label(offer)}: reservada ahora"


def booked_news(offer: Offer) -> str:
    return f"🎉 {_label(offer)}: reservada"


def failed_line(offer: Offer, error: Exception) -> str:
    return f"❌ {_label(offer)}: error al reservar ({error})"


def failed_news(offer: Offer, error: Exception) -> str:
    return f"❌ {_label(offer)}: no he podido reservarla ({error})"


def credits(live: Sequence[Pack]) -> str:
    if not live:
        return "Créditos: no tienes ningún bono en vigor"
    return "Créditos: " + ", ".join(f"{_count(p)} (bono {_span(p)})" for p in live)


def empty(pack: Pack) -> str:
    return f"🪫 Bono {_span(pack)} agotado"


def low(pack: Pack) -> str:
    return f"🔋 Quedan {pack.credits} créditos en el bono {_span(pack)}"


def picture(lines: Sequence[str], credits: str, published_until: dt.datetime | None) -> str:
    body = "\n".join(lines) or NOTHING_PUBLISHED
    text = f"bsport\n{body}\n{credits}"
    if published_until is not None:
        day = f"{WEEKDAYS[published_until.weekday()]} {published_until:%d/%m}"
        text += f"\nTus clases están publicadas hasta el {day}"
    return text


def news(items: Sequence[str], credits: str) -> str:
    return "\n".join([*items, credits])


def fatal(notes: Sequence[str], error: Exception) -> str:
    why = str(error) or type(error).__name__
    return "\n".join([*notes, f"❌ bsport: no he podido mirar las clases. {why}"])


def unsaved(path: Path) -> str:
    return f"❌ bsport: no puedo guardar {path}; aviso una vez al día hasta arreglarlo."


def unreadable(path: Path, error: Exception) -> str:
    return f"⚠️ bsport: {path} está corrupto ({error}); lo apartará la próxima pasada normal."


def set_aside(path: Path, error: Exception, moved_to: str | None) -> str:
    if moved_to is None:
        return f"❌ bsport: {path} no se puede leer ({error}) ni apartar; empiezo sin memoria."
    return f"⚠️ bsport: {path} estaba corrupto ({error}); lo he apartado a {moved_to}."


def studio(title: str, establishment: int, listings: Sequence[Listing]) -> str:
    company = next((x.company for x in listings if x.company), "?")
    slots: dict[str, set[tuple[int, str]]] = {}
    for x in listings:
        slots.setdefault(x.activity or "?", set()).add((x.start.weekday(), f"{x.start:%H:%M}"))
    lines = [title, f"  company = {company}", f"  establishment = {establishment}"]
    for name, times in sorted(slots.items()):
        lines.append(f"  {name}: {', '.join(f'{WEEKDAYS[d]} {t}' for d, t in sorted(times))}")
    return "\n".join(lines)


def discover_failed(error: Exception) -> str:
    return f"bsport: {error}"
