"""From bsport's JSON to domain values. Pure functions."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...domain import Listing, Offer, Pack
from ...ports import Response

Row = dict[str, Any]
DEFAULT_TZ = ZoneInfo("Europe/Madrid")


def local_start(stamp: str, zone: object) -> dt.datetime:
    """The class start on the studio's wall clock, whatever offset bsport wrote it in."""
    start = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    try:
        tz = ZoneInfo(str(zone)) if zone else None
    except (ZoneInfoNotFoundError, ValueError):
        tz = None
    if start.tzinfo is None:
        return start.replace(tzinfo=tz or DEFAULT_TZ)
    return start.astimezone(tz) if tz else start


def _count(value: Any) -> int:
    return int(float(value))


def offers(rows: Iterable[Row]) -> list[Offer]:
    return [
        Offer(
            id=int(o["id"]),
            name=str(o.get("activity_name") or ""),
            start=local_start(o["date_start"], o.get("timezone_name")),
            available=bool(o.get("available")),
            full=bool(o.get("full")),
            credits=_count(o.get("credit_price") or 0),
        )
        for o in rows
    ]


def packs(rows: Iterable[Row]) -> list[Pack]:
    return [
        Pack(
            id=int(p["id"]),
            start=dt.date.fromisoformat(p["starting_date"]),
            end=dt.date.fromisoformat(p["ending_date"]),
            credits=None if p.get("available_credits") is None else _count(p["available_credits"]),
            disabled=bool(p.get("disabled")),
        )
        for p in rows
        if p.get("starting_date") and p.get("ending_date")
    ]


def listings(rows: Iterable[Row]) -> list[Listing]:
    return [
        Listing(
            company=str(o.get("company") or ""),
            activity=str(o.get("activity_name") or ""),
            start=dt.datetime.fromisoformat(o["date_start"]),
        )
        for o in rows
    ]


def booked(rows: Iterable[Row]) -> set[int]:
    return {int(b["offer"]["id"]) for b in rows if b.get("status")}


def studios(rows: Iterable[Row]) -> dict[int, str]:
    found: dict[int, str] = {}
    for b in rows:
        place = ((b.get("offer") or {}).get("activity") or {}).get("etablissement") or {}
        if place.get("id"):
            found[int(place["id"])] = str(place.get("title") or "")
    return found


def detail(res: Response) -> str:
    try:
        payload = json.loads(res.body)
    except ValueError:
        return res.text()[:120].strip()
    return json.dumps(payload, ensure_ascii=False)[:200]
