from __future__ import annotations

import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from .domain.models import Wanted, plain

# The clock the run goes by, and a studio's zone when bsport names none.
TZ = ZoneInfo("Europe/Madrid")


class ConfigError(Exception):
    pass


DAYS = {
    "lunes": 0, "monday": 0,
    "martes": 1, "tuesday": 1,
    "miercoles": 2, "wednesday": 2,
    "jueves": 3, "thursday": 3,
    "viernes": 4, "friday": 4,
    "sabado": 5, "saturday": 5,
    "domingo": 6, "sunday": 6,
}  # fmt: skip


@dataclass(frozen=True)
class Config:
    company: int
    establishment: int
    classes: tuple[Wanted, ...]
    horizon_days: int
    low_credits: int
    credentials: Path
    state: Path
    slack_token: str
    slack_channel: str


def _here(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _wanted(raw: dict[str, object], where: str) -> Wanted:
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ConfigError(f"{where}: `name` is required")
    days_raw = raw.get("days")
    if not isinstance(days_raw, list) or not days_raw:
        raise ConfigError(f"{where}: `days` must be a non-empty list")
    days = set()
    for day in days_raw:
        if plain(str(day)) not in DAYS:
            raise ConfigError(f"{where}: unknown day {day!r}")
        days.add(DAYS[plain(str(day))])
    time = str(raw.get("time", ""))
    if not re.fullmatch(r"\d{1,2}:\d{2}", time):
        raise ConfigError(f"{where}: `time` must look like 11:00")
    try:
        at = dt.time.fromisoformat(time.zfill(5))
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}") from exc
    return Wanted(name, frozenset(days), at)


def load(path: Path) -> Config:
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    base = path.parent
    try:
        company, establishment = int(raw["company"]), int(raw["establishment"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: `company` and `establishment` must be numbers") from exc
    blocks = raw.get("class", [])
    if not isinstance(blocks, list) or not all(isinstance(c, dict) for c in blocks):
        raise ConfigError(f"{path}: classes go in [[class]] blocks")
    classes = tuple(_wanted(c, f"{path} [[class]] #{i + 1}") for i, c in enumerate(blocks))
    if not classes:
        raise ConfigError(f"{path}: add at least one [[class]]")
    slack = raw.get("slack", {})
    if not isinstance(slack, dict):
        raise ConfigError(f"{path}: `slack` must be a table")
    try:
        horizon, low = int(raw.get("horizon_days", 60)), int(raw.get("low_credits", 2))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{path}: `horizon_days` and `low_credits` must be numbers") from exc
    if not 1 <= horizon <= 90:
        raise ConfigError(f"{path}: `horizon_days` must be between 1 and 90")
    return Config(
        company=company,
        establishment=establishment,
        classes=classes,
        horizon_days=horizon,
        low_credits=low,
        credentials=_here(base, str(raw.get("credentials", "credentials"))),
        state=_here(base, str(raw.get("state", "state.json"))),
        slack_token=str(slack.get("token", "")),
        slack_channel=str(slack.get("channel", "")),
    )


def read_credentials(path: Path) -> tuple[str, str]:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ConfigError(f"credentials: {exc}") from exc
    pairs = {k.strip(): v for k, v in (line.split("=", 1) for line in lines if "=" in line)}
    email, password = pairs.get("email", "").strip(), pairs.get("password", "")
    if not email or not password:
        raise ConfigError(f"{path}: needs `email=` and `password=` lines")
    return email, password
