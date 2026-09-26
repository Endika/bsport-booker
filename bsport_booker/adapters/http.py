"""The one door to the network."""

from __future__ import annotations

import http.cookiejar
import urllib.error
import urllib.request

from ..ports import Response


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class UrllibTransport:
    """Keeps cookies across calls and never follows redirects: the login token rides in one."""

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
                return Response(res.status, res.read(), dict(res.headers.items()))
        except urllib.error.HTTPError as err:
            return Response(err.code, err.read(), dict(err.headers.items()))
