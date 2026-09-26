"""A whole cron run, with the gates that keep it from spamming Slack or going silent."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from enum import Enum, auto

from ..config import Config
from ..ports import BookingGateway, BsportError, DailyGate, Notifier, StateError, StateStore
from . import messages
from .booking import Report, book_due
from .discover import discover
from .memory import Topic, remember

log = logging.getLogger(__name__)


class Mode(Enum):
    BOOK = auto()
    DRY_RUN = auto()
    STATUS = auto()
    DISCOVER = auto()


@dataclass(frozen=True)
class Outcome:
    ok: bool
    text: str = ""  # for the terminal and the log; empty when there is nothing to say


@dataclass(frozen=True)
class Tick:
    mode: Mode
    bsport: BookingGateway
    notifier: Notifier | None  # None: nobody to tell
    store: StateStore
    unsaved_gate: DailyGate
    config: Config
    now: dt.datetime

    @property
    def looking(self) -> bool:
        return self.mode is not Mode.BOOK

    def run(self) -> Outcome:
        state, notes = self._recall()
        try:
            if self.mode is Mode.DISCOVER:
                ok, found = discover(self.bsport, self.now.date())
                return Outcome(ok, "\n".join([*notes, *found]))
            self.bsport.login()
            report = book_due(self.bsport, self.config, state, now=self.now, dry_run=self.looking)
        except Exception as exc:
            log.exception("run aborted")
            return Outcome(False, self._fatal(exc, notes, state))
        if self.looking:
            return self._show(report, notes)
        return self._announce(report, notes, state)

    def _recall(self) -> tuple[dict[str, str], list[str]]:
        try:
            return self.store.load(), []
        except StateError as exc:
            # Only a real run owns the state: a look leaves the evidence where it is.
            if self.looking:
                return {}, [messages.unreadable(self.config.state, exc)]
            moved = self.store.set_aside(self.now)
            return {}, [messages.set_aside(self.config.state, exc, moved)]

    def _fatal(self, exc: Exception, notes: list[str], state: dict[str, str]) -> str:
        # However often cron runs it, one message a day per kind of failure is plenty.
        status = exc.status if isinstance(exc, BsportError) else ""
        key = Topic.FATAL.key(f"{self.now:%Y-%m-%d}", type(exc).__name__, status)
        text = messages.fatal(notes, exc)
        if self.looking:
            self._tell(text)
        elif key not in state and self._tell(text):
            self.store.save({**state, key: self.now.date().isoformat()})
        return text

    def _show(self, report: Report, notes: list[str]) -> Outcome:
        picture = messages.picture(report.lines, report.credits, report.published_until)
        text = "\n".join([*notes, picture])
        if self.mode is Mode.STATUS:
            self._tell(text)
        banner = messages.DRY_RUN if self.mode is Mode.DRY_RUN else ""
        return Outcome(not report.failed, banner + text)

    def _announce(self, report: Report, notes: list[str], state: dict[str, str]) -> Outcome:
        for line in report.lines:
            log.info("%s", line)
        news = [*notes, *(text for _, text in report.news)]
        # Without a state every run looks new, so a state that cannot be written may speak once
        # a day, by the unsaved gate, instead of repeating itself on every run.
        writable = self.store.save(state)
        if not writable:
            news.append(messages.unsaved(self.config.state))
        announced = True
        text = messages.news(news, report.credits) if news else ""
        if news and (writable or self.unsaved_gate.first_today(self.now.date())):
            announced = self._tell(text)
        state = remember(state, report, self.now.date(), announced=announced)
        saved = writable and self.store.save(state)
        return Outcome(saved and announced and not report.failed, text)

    def _tell(self, text: str) -> bool:
        if self.mode is Mode.DRY_RUN or self.notifier is None:
            return True
        return self.notifier.send(text)
