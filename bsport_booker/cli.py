from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from . import booker, slack
from .client import Bsport, BsportError
from .config import ConfigError, load, read_credentials
from .http import Transport, UrllibTransport

log = logging.getLogger("bsport_booker")
TZ = ZoneInfo("Europe/Madrid")


def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    now: dt.datetime | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="bsport-booker")
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="look, book nothing, tell nobody")
    mode.add_argument("--status", action="store_true", help="send the full picture to Slack")
    mode.add_argument(
        "--discover", action="store_true", help="list your studios, their ids and their classes"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        config = load(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    now = now or dt.datetime.now(TZ)
    http = transport or UrllibTransport()
    looking = args.dry_run or args.status or args.discover

    def say(text: str) -> bool:
        return _say(http, config.slack_token, config.slack_channel, text, quiet=args.dry_run)

    notes: list[str] = []
    try:
        state = booker.load_state(config.state)
    except booker.StateError as exc:
        state = {}
        notes.append(_set_aside(config.state, now, exc))

    client = Bsport(http)
    try:
        email, password = read_credentials(config.credentials)
        if args.discover:
            return _discover(client, email, password, now.date())
        client.login(email, password)
        report = booker.run(client, config, state, now=now, dry_run=looking)
    except Exception as exc:
        log.exception("run aborted")
        # Cron runs this every half hour: one message a day per kind of failure is plenty.
        kind = f"{type(exc).__name__}:{exc.status if isinstance(exc, BsportError) else ''}"
        key = f"fatal:{now:%Y-%m-%d}:{kind}"
        text = "\n".join([*notes, f"❌ bsport: no he podido mirar las clases. {exc or kind}"])
        print(text)
        if (key not in state or looking) and say(text) and not looking:
            state[key] = now.date().isoformat()
            _save(config.state, state)
        return 1

    if looking:
        body = "\n".join(report.lines) or "No hay ninguna de tus clases publicada todavía."
        text = f"bsport\n{body}\n{report.credits}"
        if report.published_until:
            text += f"\nCalendario publicado hasta el {report.published_until}"
        print(("(simulado, no se ha reservado nada)\n" if args.dry_run else "") + text)
        if args.status:
            say(text)
        return 1 if report.failed else 0

    for line in report.lines:
        log.info("%s", line)
    news = [*notes, *(text for _, text in report.news)]
    # Without a state every run looks new, so a state that cannot be written may speak only in
    # the one run a day at 08:00, instead of repeating itself every half hour.
    writable = _save(config.state, state)
    if not writable:
        news.append(
            f"❌ bsport: no puedo guardar {config.state}; hasta que se arregle, aviso a las 8."
        )
    announced = True
    if news:
        text = "\n".join([*news, report.credits])
        print(text)
        if writable or _morning(now):
            announced = say(text)
    booker.commit(state, report, now.date(), announced=announced)
    saved = writable and _save(config.state, state)
    return 0 if saved and announced and not report.failed else 1


def _morning(now: dt.datetime) -> bool:
    return now.hour == 8 and now.minute < 30


def _set_aside(path: Path, now: dt.datetime, exc: Exception) -> str:
    corrupt = path.with_name(f"{path.name}.corrupt-{now:%Y%m%d%H%M}")
    try:
        path.replace(corrupt)
    except OSError:
        return f"❌ bsport: {path} no se puede leer ({exc}) ni apartar; empiezo sin memoria."
    return f"⚠️ bsport: {path} estaba corrupto ({exc}); lo he apartado a {corrupt.name}."


def _discover(client: Bsport, email: str, password: str, today: dt.date) -> int:
    try:
        client.login(email, password)
        studios = client.studios()
        if not studios:
            print("No upcoming bookings, so bsport won't say which studios are yours. Book one.")
            return 1
        for establishment, title in sorted(studios.items()):
            offers = client.raw_offers(establishment, today, today + dt.timedelta(days=14))
            company = next((o.get("company") for o in offers if o.get("company")), "?")
            print(f"{title}\n  company = {company}\n  establishment = {establishment}")
            slots: dict[str, set[str]] = {}
            for o in offers:
                start = dt.datetime.fromisoformat(o["date_start"])
                slot = f"{booker.WEEKDAYS[start.weekday()]} {start:%H:%M}"
                slots.setdefault(str(o.get("activity_name") or "?"), set()).add(slot)
            for name, times in sorted(slots.items()):
                print(f"  {name}: {', '.join(sorted(times, key=_slot_order))}")
    except (BsportError, KeyError, ValueError) as exc:
        print(f"bsport: {exc}")
        return 1
    return 0


def _slot_order(slot: str) -> tuple[int, str]:
    day, time = slot.split(" ")
    return booker.WEEKDAYS.index(day), time


def _say(http: Transport, token: str, channel: str, text: str, *, quiet: bool = False) -> bool:
    if quiet or not (token and channel):
        return True
    return slack.send(http, token, channel, text)


def _save(path: Path, state: dict[str, str]) -> bool:
    try:
        booker.save_state(path, state)
    except OSError as exc:
        log.error("could not save state: %s", exc)
        return False
    return True


if __name__ == "__main__":
    sys.exit(main())
