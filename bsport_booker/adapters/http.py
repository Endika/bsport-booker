"""The one door to the network."""

from __future__ import annotations

import http.cookiejar
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class Transport(Protocol):
    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None = None
    ) -> Response: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Followed, a redirect would carry the token to another host and turn the booking POST
    # into a GET whose 200 reads as success. Refused, it comes back as the 3xx it is.
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class UrllibTransport:
    def __init__(self, timeout: float = 30) -> None:
        self._timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect()
        )

    def request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None = None
    ) -> Response:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=self._timeout) as res:
                return Response(res.status, res.read())
        # urllib raises on 3xx, 4xx and 5xx; the callers want those as answers.
        except urllib.error.HTTPError as err:
            return Response(err.code, err.read())
