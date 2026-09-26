import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bsport_booker.adapters.http import UrllibTransport


class Redirecting(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path == "/elsewhere":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(302)
        self.send_header("Location", "/elsewhere")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def loopback() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirecting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_a_redirect_comes_back_as_the_3xx_it_is_and_is_never_followed(loopback):
    res = UrllibTransport(timeout=5).request(
        "POST", f"{loopback}/book", headers={"Authorization": "Token t"}, body=b"{}"
    )

    assert res.status == 302
