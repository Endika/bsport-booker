"""Slack messages through a bot token (`chat:write`)."""

from __future__ import annotations

import json
import logging

from .http import Transport

log = logging.getLogger(__name__)
API = "https://slack.com/api/chat.postMessage"


class Slack:
    def __init__(self, transport: Transport, token: str, channel: str) -> None:
        self._http = transport
        self._token = token
        self._channel = channel

    def send(self, text: str) -> bool:
        try:
            res = self._http.request(
                "POST",
                API,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                body=json.dumps({"channel": self._channel, "text": text}).encode(),
            )
        except OSError as exc:
            log.error("Slack is unreachable: %s", exc)
            return False
        try:
            payload = json.loads(res.body)
        except ValueError:
            log.error("Slack answered HTTP %s with no JSON", res.status)
            return False
        # Slack answers 200 with `ok: false` on failure, so the status code is not enough.
        if not payload.get("ok"):
            log.error("Slack answered an error: %s", payload.get("error"))
            return False
        return True
