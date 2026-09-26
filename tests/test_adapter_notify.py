from bsport_booker.adapters.notify import Slack
from bsport_booker.adapters.notify.slack import API
from bsport_booker.ports import Response

from .fakes import Scripted, Unreachable, json_response


def test_a_message_goes_to_the_channel_with_the_bot_token():
    slack = Scripted({API: json_response({"ok": True})})

    assert Slack(slack, "xoxb-1", "C1").send("hola")

    [(method, _, headers, body)] = slack.requests
    assert (method, headers["Authorization"], body) == (
        "POST",
        "Bearer xoxb-1",
        {"channel": "C1", "text": "hola"},
    )


def test_a_200_with_ok_false_is_a_failure(caplog):
    slack = Scripted({API: json_response({"ok": False, "error": "channel_not_found"})})

    assert not Slack(slack, "xoxb-1", "C1").send("hola")
    assert "channel_not_found" in caplog.text


def test_an_answer_that_is_not_json_is_a_failure():
    slack = Scripted({API: Response(502, b"<html>bad gateway</html>")})

    assert not Slack(slack, "xoxb-1", "C1").send("hola")


def test_an_unreachable_slack_is_a_failure_not_a_crash():
    assert not Slack(Unreachable(), "xoxb-1", "C1").send("hola")
