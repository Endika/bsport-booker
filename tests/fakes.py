"""bsport and Slack in memory, behind the same `Transport` the real adapters use."""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from bsport_booker.adapters.bsport.http import API, LOGIN
from bsport_booker.ports import Response

TOKEN = "tok-abc"
MEMBER = 7
COMPANY = 1234
ESTABLISHMENT = 5678


@dataclass
class FakeBsport:
    email: str = "me@example.org"
    password: str = "s3cret"
    offers: list[dict[str, Any]] = field(default_factory=list)
    packs: list[dict[str, Any]] = field(default_factory=list)
    bookings: list[int] = field(default_factory=list)
    page_size: int = 1000
    hide_next: bool = False  # the real offer list once promised 446 and linked no page 2
    studio: dict[str, Any] = field(default_factory=dict)
    book_status: int = 201
    slack_ok: bool = True
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    _next: int = 1000

    def offer(
        self, when: str, name: str = "FUNCTIONAL TRAINING", *, available: bool = True,
        full: bool = False, credits: int = 1,
    ) -> dict[str, Any]:  # fmt: skip
        self._next += 1
        offer = {
            "id": self._next,
            "activity_name": name,
            "date_start": f"{when}:00+02:00",
            "available": available,
            "full": full,
            "credit_price": credits,
        }
        self.offers.append(offer)
        return offer

    def pack(self, start: str, end: str, credits: int, *, disabled: bool = False) -> dict[str, Any]:
        self._next += 1
        pack = {
            "id": self._next,
            "starting_date": start,
            "ending_date": end,
            "available_credits": credits,
            "disabled": disabled,
        }
        self.packs.append(pack)
        return pack

    def posted(self, what: str) -> list[Any]:
        return [body for method, path, body in self.calls if method == "POST" and what in path]

    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None = None
    ) -> Response:
        payload = json.loads(body) if body else None
        if url.startswith("https://slack.com/"):
            self.calls.append((method, "slack", payload))
            return json_response({"ok": self.slack_ok})
        parts = urllib.parse.urlsplit(url)
        path = parts.path.removeprefix(urllib.parse.urlsplit(API).path)
        query = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((method, path, payload))
        if url == LOGIN:
            ok = payload == {"email": self.email, "password": self.password}
            return json_response(
                {"token": TOKEN} if ok else {"detail": "bad credentials"}, 200 if ok else 400
            )
        if headers.get("Authorization") != f"Token {TOKEN}":
            return json_response({"detail": "unauthorized"}, 401)
        return self._route(method, path, query, payload, url)

    def _page(self, items: list[dict[str, Any]], query: dict[str, str], url: str) -> Response:
        page = int(query.get("page", 1))
        chunk = items[(page - 1) * self.page_size : page * self.page_size]
        more = page * self.page_size < len(items)
        base = url.split("&page=", 1)[0]
        following = f"{base}&page={page + 1}" if more and not self.hide_next else None
        if "/book/v1/offer/" in url:  # the real one nests it
            return json_response(
                {"count": len(items), "results": chunk, "links": {"next": following}}
            )
        return json_response(
            {
                "count": len(items),
                "results": chunk,
                "next": following,
            }
        )

    def _route(
        self, method: str, path: str, query: dict[str, str], body: Any, url: str
    ) -> Response:
        if (method, path) == ("GET", "/core-data/v1/member/") and query.get("me") == "true":
            return self._page([{"id": MEMBER}], query, url)
        if (method, path) == ("GET", "/api-v0/booking/future/"):
            rows = [
                {"offer": {"id": o, "activity": {"etablissement": self.studio}}, "status": True}
                for o in self.bookings
            ]
            return self._page(rows, query, url)
        if (method, path) == ("GET", "/buyable/v1/payment-pack/consumer-payment-pack/"):
            assert query.get("member") == str(MEMBER)
            return json_response(self.packs)  # the real one is not paginated either
        if (method, path) == ("GET", "/book/v1/offer/"):
            assert query["establishment"] == str(ESTABLISHMENT)
            assert query.get("company", str(COMPANY)) == str(COMPANY)
            first, last = (
                dt.date.fromisoformat(query["min_date"]),
                dt.date.fromisoformat(query["max_date"]),
            )
            hits = [
                o
                for o in self.offers
                if first <= dt.date.fromisoformat(o["date_start"][:10]) <= last
            ]
            return self._page(hits, query, url)
        if m := re.fullmatch(
            r"/buyable/v1/payment-pack/consumer-payment-pack/(\d+)/register_booking/", path
        ):
            if self.book_status >= 300:
                return json_response({"error": "nope"}, self.book_status)
            pack = next(p for p in self.packs if p["id"] == int(m[1]))
            offer = next(o for o in self.offers if o["id"] == body["offer"])
            if pack["available_credits"] is not None:
                pack["available_credits"] -= int(float(offer["credit_price"]))
            self.bookings.append(offer["id"])
            return json_response(
                {"id": pack["id"], "available_credits": pack["available_credits"]}, self.book_status
            )
        return json_response({"detail": f"no route {method} {path}"}, 404)


@dataclass
class Scripted:
    """Answers each URL with a canned response, for shapes FakeBsport never produces."""

    answers: dict[str, Response]
    requests: list[tuple[str, str, dict[str, str], Any]] = field(default_factory=list)

    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None = None
    ) -> Response:
        self.requests.append((method, url, headers, json.loads(body) if body else None))
        return self.answers.get(url, json_response({"detail": "no such page"}, 404))


class Unreachable:
    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None = None
    ) -> Response:
        raise TimeoutError("timed out")


def json_response(payload: Any, status: int = 200) -> Response:
    return Response(status, json.dumps(payload).encode(), {"Content-Type": "application/json"})
