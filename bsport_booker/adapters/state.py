"""The state as a JSON file written through a temp file and fsync, and a daily marker."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

from ..ports import StateError

log = logging.getLogger(__name__)


class JsonFileState:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, str]:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise StateError(str(exc)) from exc
        if not isinstance(raw, dict):
            raise StateError("not a JSON object")
        return {str(k): str(v) for k, v in raw.items()}

    def set_aside(self, now: dt.datetime) -> str | None:
        corrupt = self._path.with_name(f"{self._path.name}.corrupt-{now:%Y%m%d%H%M}")
        try:
            self._path.replace(corrupt)
        except OSError:
            return None
        return corrupt.name

    def save(self, state: dict[str, str]) -> bool:
        try:
            self._write(state)
        except OSError as exc:
            log.error("could not save state: %s", exc)
            return False
        return True

    def _write(self, state: dict[str, str]) -> None:
        tmp = self._path.with_suffix(".tmp")
        # A leftover tmp would keep its old mode through the rename, so start from scratch.
        tmp.unlink(missing_ok=True)
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
            out.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
        tmp.replace(self._path)


class DailyMarker:
    """A file per day, outside the state's directory: it has to work when that one doesn't."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def first_today(self, day: dt.date) -> bool:
        marker = self._directory / f"bsport-booker-unsaved-{day:%Y%m%d}"
        try:
            marker.touch(exist_ok=False)
        except FileExistsError:
            return False
        except OSError:
            return True  # can't keep track anywhere: better noisy than silent
        return True
