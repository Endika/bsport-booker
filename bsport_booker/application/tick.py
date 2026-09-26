"""A whole cron run, with the gates that keep it from spamming Slack or going silent."""

from __future__ import annotations

import datetime as dt
import logging
import tempfile
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from ..config import Config, read_credentials
from ..ports import BookingGateway, BsportError, Notifier, StateError, StateStore
from . import messages
from .booking import Report, book_due
from .discover import discover
from .memory import remember

log = logging.getLogger(__name__)


class Mode(Enum):
    BOOK = auto()
    DRY_RUN = auto()
    STATUS = auto()
    DISCOVER = auto()


@dataclass(frozen=True)
class Tick:
    bsport: BookingGateway
    notifier: Notifier | None  # None: nobody to tell
    store: StateStore
    config: Config
    now: dt.datetime

    def run(self, mode: Mode) -> bool:
        state, notes = self._recall()
        try:
            email, password = read_credentials(self.config.credentials)
            if mode is Mode.DISCOVER:
                return discover(self.bsport, email, password, self.now.date())
            self.bsport.login(email, password)
            report = book_due(
                self.bsport, self.config, state, now=self.now, dry_run=mode is not Mode.BOOK
            )
        except Exception as exc:
            log.exception("run aborted")
            self._fatal(exc, notes, state, looking=mode is not Mode.BOOK)
            return False
        if mode is Mode.BOOK:
            return self._announce(report, notes, state)
        return self._show(report, mode)

    def _recall(self) -> tuple[dict[str, str], list[str]]:
        try:
            return self.store.load(), []
        except StateError as exc:
            moved = self.store.set_aside(self.now)
            return {}, [messages.set_aside(self.config.state, exc, moved)]

    def _fatal(
        self, exc: Exception, notes: list[str], state: dict[str, str], *, looking: bool
    ) -> None:
        # However often cron runs it, one message a day per kind of failure is plenty.
        kind = f"{type(exc).__name__}:{exc.status if isinstance(exc, BsportError) else ''}"
        key = f"fatal:{self.now:%Y-%m-%d}:{kind}"
        text = messages.fatal(notes, exc)
        print(text)
        if looking:
            self._tell(text)
        elif key not in state and self._tell(text):
            self.store.save({**state, key: self.now.date().isoformat()})

    def _show(self, report: Report, mode: Mode) -> bool:
        text = messages.picture(report.lines, report.credits, report.published_until)
        print((messages.DRY_RUN if mode is Mode.DRY_RUN else "") + text)
        if mode is Mode.STATUS:
            self._tell(text)
        return not report.failed

    def _announce(self, report: Report, notes: list[str], state: dict[str, str]) -> bool:
        for line in report.lines:
            log.info("%s", line)
        news = [*notes, *(text for _, text in report.news)]
        # Without a state every run looks new, so a state that cannot be written may speak once
        # a day, kept track of in the temp dir, instead of repeating itself on every run.
        writable = self.store.save(state)
        if not writable:
            news.append(messages.unsaved(self.config.state))
        announced = True
        if news:
            text = messages.news(news, report.credits)
            print(text)
            if writable or _first_today(self.now):
                announced = self._tell(text)
        state = remember(state, report, self.now.date(), announced=announced)
        saved = writable and self.store.save(state)
        return saved and announced and not report.failed

    def _tell(self, text: str) -> bool:
        return self.notifier is None or self.notifier.send(text)


def _first_today(now: dt.datetime) -> bool:
    marker = Path(tempfile.gettempdir()) / f"bsport-booker-unsaved-{now:%Y%m%d}"
    try:
        marker.touch(exist_ok=False)
    except FileExistsError:
        return False
    except OSError:
        return True  # can't keep track anywhere: better noisy than silent
    return True
