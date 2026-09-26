"""Client for bsport, speaking to its API the way the web app does, as a member."""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .domain import Offer, Pack
from .http import Response, Transport

API = "https://api.production.bsport.io"
LOGIN = f"{API}/platform/v1/authentication/signin/with-login/"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) bsport-booker"
MAX_PAGES = 20
DEFAULT_TZ = ZoneInfo("Europe/Madrid")


class BsportError(Exception):
    def __init__(self, what: str, status: int, detail: str = "") -> None:
        super().__init__(f"{what}: HTTP {status} {detail}".rstrip())
        self.status = status


def _local(stamp: str, zone: object) -> dt.datetime:
    """The class start on the studio's wall clock, whatever offset bsport wrote it in."""
    start = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    try:
        tz = ZoneInfo(str(zone)) if zone else None
    except (ZoneInfoNotFoundError, ValueError):
        tz = None
    if start.tzinfo is None:
        return start.replace(tzinfo=tz or DEFAULT_TZ)
    return start.astimezone(tz) if tz else start


def _detail(res: Response) -> str:
    try:
        payload = json.loads(res.body)
    except ValueError:
        return res.text()[:120].strip()
    return json.dumps(payload, ensure_ascii=False)[:200]


class Bsport:
    def __init__(self, transport: Transport) -> None:
        self._http = transport
        self._token = ""

    def _call(self, what: str, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Origin": "https://backoffice.bsport.io",
        }
        if self._token:
            headers["Authorization"] = f"Token {self._token}"
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()
        try:
            res = self._http.request(method, url, headers=headers, body=body)
        except OSError as exc:
            raise BsportError(what, 0, f"network: {exc}") from exc
        if not 200 <= res.status < 300:
            raise BsportError(what, res.status, _detail(res))
        try:
            return json.loads(res.body) if res.body else None
        except ValueError as exc:
            raise BsportError(what, res.status, f"not JSON: {res.text()[:120]!r}") from exc

    def _pages(self, what: str, url: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        next_url: str | None = url
        for _ in range(MAX_PAGES):
            if not next_url:
                return out
            page = self._call(what, "GET", next_url)
            if isinstance(page, list):  # some endpoints (packs) skip pagination altogether
                return out + page
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise BsportError(what, 200, "unexpected shape")
            out += page["results"]
            # Offers put it under `links`; bookings and members at the top.
            next_url = page.get("next") or (page.get("links") or {}).get("next") or None
            count = page.get("count")
            if not next_url and isinstance(count, int) and len(out) < count:
                raise BsportError(what, 200, f"read {len(out)} of {count} and found no next page")
        raise BsportError(what, 200, f"more than {MAX_PAGES} pages")

    def login(self, email: str, password: str) -> None:
        res = self._call("login", "POST", LOGIN, {"email": email, "password": password})
        token = res.get("token") if isinstance(res, dict) else None
        if not token:
            raise BsportError("login", 200, "no token in the answer")
        self._token = str(token)

    def member_id(self) -> int:
        found = self._pages("member", f"{API}/core-data/v1/member/?me=true")
        if len(found) != 1:
            raise BsportError("member", 200, f"expected one member, got {len(found)}")
        return int(found[0]["id"])

    def studios(self) -> dict[int, str]:
        """Where your upcoming bookings are: the only way bsport tells a member its studios."""
        bookings = self._pages("bookings", f"{API}/api-v0/booking/future/?page_size=100")
        found: dict[int, str] = {}
        for b in bookings:
            place = ((b.get("offer") or {}).get("activity") or {}).get("etablissement") or {}
            if place.get("id"):
                found[int(place["id"])] = str(place.get("title") or "")
        return found

    def raw_offers(self, establishment: int, first: dt.date, last: dt.date) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "establishment": establishment,
                "min_date": first.isoformat(),
                "max_date": last.isoformat(),
                "page_size": 300,
            }
        )
        return self._pages("offers", f"{API}/book/v1/offer/?{query}")

    def booked_offers(self) -> set[int]:
        bookings = self._pages("bookings", f"{API}/api-v0/booking/future/?page_size=100")
        return {int(b["offer"]["id"]) for b in bookings if b.get("status")}

    def packs(self, member: int) -> list[Pack]:
        raw = self._pages(
            "packs", f"{API}/buyable/v1/payment-pack/consumer-payment-pack/?member={member}"
        )
        return [
            Pack(
                id=int(p["id"]),
                start=dt.date.fromisoformat(p["starting_date"]),
                end=dt.date.fromisoformat(p["ending_date"]),
                credits=None
                if p.get("available_credits") is None
                else int(float(p["available_credits"])),
                disabled=bool(p.get("disabled")),
            )
            for p in raw
            if p.get("starting_date") and p.get("ending_date")
        ]

    def offers(
        self, company: int, establishment: int, first: dt.date, last: dt.date
    ) -> list[Offer]:
        query = urllib.parse.urlencode(
            {
                "company": company,
                "establishment": establishment,
                "min_date": first.isoformat(),
                "max_date": last.isoformat(),
                "page_size": 300,
            }
        )
        return [
            Offer(
                id=int(o["id"]),
                name=str(o.get("activity_name") or ""),
                start=_local(o["date_start"], o.get("timezone_name")),
                available=bool(o.get("available")),
                full=bool(o.get("full")),
                credits=int(float(o.get("credit_price") or 0)),
            )
            for o in self._pages("offers", f"{API}/book/v1/offer/?{query}")
        ]

    def book(self, pack: Pack, offer: Offer) -> None:
        self._call(
            "book",
            "POST",
            f"{API}/buyable/v1/payment-pack/consumer-payment-pack/{pack.id}/register_booking/",
            {"offer": offer.id},
        )
