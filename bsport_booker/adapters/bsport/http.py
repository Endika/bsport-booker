"""Speaks to bsport's API the way the web app does, as a member."""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
from typing import Any

from ...domain.models import Listing, Offer, Pack
from ...ports import BsportError
from ..http import Transport
from . import parsing

API = "https://api.production.bsport.io"
LOGIN = f"{API}/platform/v1/authentication/signin/with-login/"
FUTURE_BOOKINGS = f"{API}/api-v0/booking/future/?page_size=100"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) bsport-booker"
MAX_PAGES = 20


class BsportGateway:
    def __init__(self, transport: Transport) -> None:
        self._http = transport
        self._token = ""

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

    def booked_offers(self) -> set[int]:
        return parsing.booked(self._pages("bookings", FUTURE_BOOKINGS))

    def studios(self) -> dict[int, str]:
        return parsing.studios(self._pages("bookings", FUTURE_BOOKINGS))

    def packs(self, member: int) -> list[Pack]:
        url = f"{API}/buyable/v1/payment-pack/consumer-payment-pack/?member={member}"
        return parsing.packs(self._pages("packs", url))

    def offers(
        self, company: int, establishment: int, first: dt.date, last: dt.date
    ) -> list[Offer]:
        rows = self._offer_rows(first, last, company=company, establishment=establishment)
        return parsing.offers(rows)

    def timetable(self, establishment: int, first: dt.date, last: dt.date) -> list[Listing]:
        return parsing.listings(self._offer_rows(first, last, establishment=establishment))

    def book(self, pack: Pack, offer: Offer) -> None:
        self._call(
            "book",
            "POST",
            f"{API}/buyable/v1/payment-pack/consumer-payment-pack/{pack.id}/register_booking/",
            {"offer": offer.id},
        )

    def _offer_rows(self, first: dt.date, last: dt.date, **scope: int) -> list[parsing.Row]:
        query = urllib.parse.urlencode(
            {**scope, "min_date": first.isoformat(), "max_date": last.isoformat(), "page_size": 300}
        )
        return self._pages("offers", f"{API}/book/v1/offer/?{query}")

    def _pages(self, what: str, url: str) -> list[parsing.Row]:
        out: list[parsing.Row] = []
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
            raise BsportError(what, res.status, parsing.detail(res))
        try:
            return json.loads(res.body) if res.body else None
        except ValueError as exc:
            raise BsportError(what, res.status, f"not JSON: {res.text()[:120]!r}") from exc
