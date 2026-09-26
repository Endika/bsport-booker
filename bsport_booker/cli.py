from __future__ import annotations

import argparse
import datetime as dt
import logging
import tempfile
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from .adapters.bsport.http import BsportGateway
from .adapters.http import Transport, UrllibTransport
from .adapters.slack import Slack
from .adapters.state import DailyMarker, JsonFileState
from .application.tick import Mode, Tick
from .config import Config, ConfigError, load, read_credentials
from .ports import Notifier

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Madrid")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bsport-booker")
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="look, book nothing, tell nobody")
    mode.add_argument("--status", action="store_true", help="send the full picture to Slack")
    mode.add_argument(
        "--discover", action="store_true", help="list your studios, their ids and their classes"
    )
    return parser


def main(
    argv: list[str] | None = None,
    transport: Transport | None = None,
    now: dt.datetime | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load(args.config)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2

    http = transport or UrllibTransport()
    tick = Tick(
        mode=_mode(args),
        bsport=BsportGateway(http, partial(read_credentials, config.credentials)),
        notifier=_slack(http, config),
        store=JsonFileState(config.state),
        unsaved_gate=DailyMarker(Path(tempfile.gettempdir())),
        config=config,
        now=now or dt.datetime.now(TZ),
    )
    outcome = tick.run()
    if outcome.text:
        print(outcome.text)
    return 0 if outcome.ok else 1


def _slack(http: Transport, config: Config) -> Notifier | None:
    if not (config.slack_token and config.slack_channel):
        return None
    return Slack(http, config.slack_token, config.slack_channel)


def _mode(args: argparse.Namespace) -> Mode:
    if args.dry_run:
        return Mode.DRY_RUN
    if args.status:
        return Mode.STATUS
    if args.discover:
        return Mode.DISCOVER
    return Mode.BOOK
