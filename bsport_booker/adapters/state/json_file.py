"""The state as a JSON file, written through a temp file and fsync."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

from ...ports import StateError

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
        with tmp.open("w") as out:
            out.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
            out.flush()
            os.fsync(out.fileno())
        tmp.replace(self._path)
