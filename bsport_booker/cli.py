from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from . import booker
from .adapters.bsport import BsportGateway
from .adapters.http import UrllibTransport
from .adapters.notify import Slack
from .adapters.state import JsonFileState
from .config import ConfigError, load, read_credentials
from .ports import BsportError, StateError, Transport

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

    slack = Slack(http, config.slack_token, config.slack_channel)

    def say(text: str) -> bool:
        if args.dry_run or not (config.slack_token and config.slack_channel):
            return True
        return slack.send(text)

    store = JsonFileState(config.state)
    notes: list[str] = []
    try:
        state = store.load()
    except StateError as exc:
        state = {}
        notes.append(_set_aside(store, config.state, now, exc))

    client = BsportGateway(http)
    try:
        email, password = read_credentials(config.credentials)
        if args.discover:
            return _discover(client, email, password, now.date())
        client.login(email, password)
        report = booker.run(client, config, state, now=now, dry_run=looking)
    except Exception as exc:
        log.exception("run aborted")
        # However often cron runs it, one message a day per kind of failure is plenty.
        kind = f"{type(exc).__name__}:{exc.status if isinstance(exc, BsportError) else ''}"
        key = f"fatal:{now:%Y-%m-%d}:{kind}"
        text = "\n".join([*notes, f"❌ bsport: no he podido mirar las clases. {exc or kind}"])
        print(text)
        if (key not in state or looking) and say(text) and not looking:
            state[key] = now.date().isoformat()
            store.save(state)
        return 1

    if looking:
        body = "\n".join(report.lines) or "No hay ninguna de tus clases publicada todavía."
        text = f"bsport\n{body}\n{report.credits}"
        if report.published_until:
            text += f"\nTus clases están publicadas hasta el {report.published_until}"
        print(("(simulado, no se ha reservado nada)\n" if args.dry_run else "") + text)
        if args.status:
            say(text)
        return 1 if report.failed else 0

    for line in report.lines:
        log.info("%s", line)
    news = [*notes, *(text for _, text in report.news)]
    # Without a state every run looks new, so a state that cannot be written may speak once a
    # day, kept track of in the temp dir, instead of repeating itself on every run.
    writable = store.save(state)
    if not writable:
        news.append(
            f"❌ bsport: no puedo guardar {config.state}; aviso una vez al día hasta arreglarlo."
        )
    announced = True
    if news:
        text = "\n".join([*news, report.credits])
        print(text)
        if writable or _first_today(now):
            announced = say(text)
    booker.commit(state, report, now.date(), announced=announced)
    saved = writable and store.save(state)
    return 0 if saved and announced and not report.failed else 1


def _first_today(now: dt.datetime) -> bool:
    marker = Path(tempfile.gettempdir()) / f"bsport-booker-unsaved-{now:%Y%m%d}"
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return False
    except OSError:
        return True  # can't keep track anywhere: better noisy than silent
    return True


def _set_aside(store: JsonFileState, path: Path, now: dt.datetime, exc: Exception) -> str:
    moved = store.set_aside(now)
    if moved is None:
        return f"❌ bsport: {path} no se puede leer ({exc}) ni apartar; empiezo sin memoria."
    return f"⚠️ bsport: {path} estaba corrupto ({exc}); lo he apartado a {moved}."


def _discover(client: BsportGateway, email: str, password: str, today: dt.date) -> int:
    try:
        client.login(email, password)
        studios = client.studios()
        if not studios:
            print("No upcoming bookings, so bsport won't say which studios are yours. Book one.")
            return 1
        for establishment, title in sorted(studios.items()):
            listings = client.timetable(establishment, today, today + dt.timedelta(days=14))
            company = next((x.company for x in listings if x.company), "?")
            print(f"{title}\n  company = {company}\n  establishment = {establishment}")
            slots: dict[str, set[str]] = {}
            for x in listings:
                slot = f"{booker.WEEKDAYS[x.start.weekday()]} {x.start:%H:%M}"
                slots.setdefault(x.activity or "?", set()).add(slot)
            for name, times in sorted(slots.items()):
                print(f"  {name}: {', '.join(sorted(times, key=_slot_order))}")
    except (BsportError, KeyError, ValueError) as exc:
        print(f"bsport: {exc}")
        return 1
    return 0


def _slot_order(slot: str) -> tuple[int, str]:
    day, time = slot.split(" ")
    return booker.WEEKDAYS.index(day), time


if __name__ == "__main__":
    sys.exit(main())
