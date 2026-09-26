from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bsport_booker.cli import main

from .fakes import COMPANY, ESTABLISHMENT, FakeBsport

NOW = dt.datetime(2026, 9, 26, 21, 0, tzinfo=ZoneInfo("Europe/Madrid"))  # a Saturday
OCTOBER = ("2026-10-09", "2026-11-08")
SEPTEMBER = ("2026-09-09", "2026-10-08")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "credentials").write_text("email=me@example.org\npassword=s3cret\n")
    (tmp_path / "config.toml").write_text(
        f"company = {COMPANY}\nestablishment = {ESTABLISHMENT}\nlow_credits = 2\n"
        "[[class]]\n"
        'name = "Functional training"\n'
        'days = ["lunes", "Miércoles", "viernes"]\n'
        'time = "11:00"\n'
        "[slack]\n"
        'token = "xoxb-1"\nchannel = "C1"\n'
    )
    return tmp_path


@pytest.fixture
def bsport() -> FakeBsport:
    return FakeBsport()


def tick(home: Path, bsport: FakeBsport, *extra: str, now: dt.datetime = NOW) -> int:
    return main(["--config", str(home / "config.toml"), *extra], transport=bsport, now=now)


def slack(bsport: FakeBsport) -> list[str]:
    return [str(body["text"]) for body in bsport.posted("slack")]


def booked_offers(bsport: FakeBsport) -> list[int]:
    return [body["offer"] for body in bsport.posted("register_booking")]


def test_books_only_the_wanted_classes_and_pays_with_the_pack_for_that_day(home, bsport):
    september = bsport.pack(*SEPTEMBER, credits=3)
    october = bsport.pack(*OCTOBER, credits=12)
    monday = bsport.offer("2026-09-28T11:00")
    friday_oct = bsport.offer("2026-10-09T11:00")
    bsport.offer("2026-09-29T11:00")  # a Tuesday
    bsport.offer("2026-09-30T12:00")  # the wrong hour
    bsport.offer("2026-09-30T11:00", "PILATES")

    assert tick(home, bsport) == 0

    assert booked_offers(bsport) == [monday["id"], friday_oct["id"]]
    assert (september["available_credits"], october["available_credits"]) == (2, 11)
    [message] = slack(bsport)
    assert "🎉 lun 28/09 11:00 Functional Training: reservada" in message
    assert "🎉 vie 09/10 11:00 Functional Training: reservada" in message
    assert "Créditos: 2 (bono 09/09–08/10), 11 (bono 09/10–08/11)" in message


def test_a_class_already_booked_is_left_alone_and_a_quiet_run_says_nothing(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    monday = bsport.offer("2026-09-28T11:00")
    bsport.bookings.append(monday["id"])

    assert tick(home, bsport) == 0

    assert booked_offers(bsport) == []
    assert slack(bsport) == []


def test_no_credits_for_a_day_is_said_once_and_is_not_a_failure(home, bsport):
    bsport.pack(*SEPTEMBER, credits=0)
    bsport.pack(*OCTOBER, credits=12)
    bsport.offer("2026-10-07T11:00")

    assert tick(home, bsport) == 0
    assert tick(home, bsport) == 0

    assert booked_offers(bsport) == []
    news = [m for m in slack(bsport) if "no te quedan créditos" in m]
    assert len(news) == 1
    assert "mié 07/10 11:00" in news[0]


def test_an_empty_pack_and_low_credits_are_each_announced_once(home, bsport):
    bsport.pack(*SEPTEMBER, credits=0)
    october = bsport.pack(*OCTOBER, credits=3)
    bsport.offer("2026-10-09T11:00")

    tick(home, bsport)
    tick(home, bsport)

    messages = "\n".join(slack(bsport))
    assert messages.count("Bono 09/09–08/10 agotado") == 1
    assert messages.count("Quedan 2 créditos en el bono 09/10–08/11") == 1
    assert october["available_credits"] == 2


def test_a_full_class_is_reported_once_and_booked_when_a_spot_frees_up(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    monday = bsport.offer("2026-09-28T11:00", full=True)

    tick(home, bsport)
    tick(home, bsport)
    assert booked_offers(bsport) == []
    monday["full"] = False
    tick(home, bsport)

    messages = slack(bsport)
    assert sum("está llena" in m for m in messages) == 1
    assert booked_offers(bsport) == [monday["id"]]
    assert "reservada" in messages[-1]


def test_a_class_the_studio_disabled_is_mentioned_once_and_never_booked(home, bsport):
    bsport.pack(*OCTOBER, credits=12)
    bsport.offer("2026-10-12T11:00", available=False)

    tick(home, bsport)
    tick(home, bsport)

    assert booked_offers(bsport) == []
    assert sum("no disponible" in m for m in slack(bsport)) == 1


def test_the_pack_that_expires_first_pays_when_two_cover_the_day(home, bsport):
    late = bsport.pack("2026-09-01", "2026-12-31", credits=10)
    soon = bsport.pack("2026-09-20", "2026-10-01", credits=10)
    bsport.offer("2026-09-28T11:00")

    tick(home, bsport)

    assert (soon["available_credits"], late["available_credits"]) == (9, 10)


def test_classes_earlier_today_are_ignored(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    bsport.offer("2026-09-28T11:00")

    tick(home, bsport, now=dt.datetime(2026, 9, 28, 11, 30, tzinfo=ZoneInfo("Europe/Madrid")))

    assert booked_offers(bsport) == []


def test_a_refused_booking_fails_the_run_and_is_reported_once(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    bsport.offer("2026-09-28T11:00")
    bsport.book_status = 400

    assert tick(home, bsport) == 1
    assert tick(home, bsport) == 1

    assert sum("no he podido reservarla" in m for m in slack(bsport)) == 1


def test_a_failed_login_is_reported_once_a_day(home, bsport):
    bsport.password = "changed"

    assert tick(home, bsport) == 1
    assert tick(home, bsport) == 1
    assert tick(home, bsport, now=NOW + dt.timedelta(days=1)) == 1

    assert len(slack(bsport)) == 2
    assert "no he podido mirar las clases" in slack(bsport)[0]


def test_a_network_failure_is_reported_not_a_crash(home, bsport, monkeypatch):
    def down(*args: object, **kwargs: object) -> None:
        raise TimeoutError("timed out")

    real = bsport.request
    monkeypatch.setattr(
        bsport,
        "request",
        lambda method, url, **kw: down() if "/book/v1/offer/" in url else real(method, url, **kw),
    )

    assert tick(home, bsport) == 1

    assert "network: timed out" in slack(bsport)[0]


def test_dry_run_books_nothing_saves_nothing_and_tells_nobody(home, bsport, capsys):
    bsport.pack(*SEPTEMBER, credits=5)
    bsport.offer("2026-09-28T11:00")

    assert tick(home, bsport, "--dry-run") == 0

    assert [m for m, path, _ in bsport.calls if m == "POST"] == ["POST"]  # the login
    assert not (home / "state.json").exists()
    out = capsys.readouterr().out
    assert "simulado" in out
    assert "➕ lun 28/09 11:00 Functional Training: la reservaría (bono hasta 08/10)" in out


def test_status_sends_the_whole_picture_and_books_nothing(home, bsport):
    bsport.pack(*SEPTEMBER, credits=0)
    bsport.pack(*OCTOBER, credits=12)
    booked = bsport.offer("2026-09-28T11:00")
    bsport.bookings.append(booked["id"])
    bsport.offer("2026-10-07T11:00")
    bsport.offer("2026-10-21T11:00")

    assert tick(home, bsport, "--status") == 0

    assert booked_offers(bsport) == []
    [message] = slack(bsport)
    assert "✅ lun 28/09 11:00 Functional Training: reservada" in message
    assert "⚠️ mié 07/10 11:00 Functional Training: sin créditos para ese día" in message
    assert "➕ mié 21/10 11:00 Functional Training: la reservaría" in message
    assert "Calendario publicado hasta el mié 21/10" in message


def test_every_page_of_offers_is_read(home, bsport):
    bsport.pack(*OCTOBER, credits=12)
    bsport.page_size = 2
    for day in ("09", "14", "16", "19", "21"):
        bsport.offer(f"2026-10-{day}T11:00")

    tick(home, bsport)

    assert len(booked_offers(bsport)) == 5


def test_a_corrupt_state_file_is_reported(home, bsport):
    (home / "state.json").write_text("{nope")

    assert tick(home, bsport) == 1

    assert "corrupto" in slack(bsport)[0]
    assert bsport.calls[:-1] == []


@pytest.mark.parametrize(
    ("line", "error"),
    [('days = ["lunes", "funday"]', "unknown day"), ('time = "11h"', "must look like")],
)
def test_a_bad_class_is_rejected_before_touching_the_network(home, bsport, line, error, caplog):
    config = home / "config.toml"
    text = config.read_text()
    key = line.split(" ", 1)[0]
    config.write_text("\n".join(line if row.startswith(key) else row for row in text.splitlines()))

    assert tick(home, bsport) == 2

    assert bsport.calls == []
    assert error in caplog.text


def test_discover_lists_studios_ids_and_class_slots(home, bsport, capsys):
    monday = bsport.offer("2026-09-28T11:00")
    bsport.offer("2026-09-30T19:30", "PILATES")
    for o in bsport.offers:
        o["company"] = COMPANY
    bsport.bookings.append(monday["id"])
    bsport.studio = {"id": ESTABLISHMENT, "title": "Estudio Demo"}

    assert tick(home, bsport, "--discover") == 0

    out = capsys.readouterr().out
    assert f"Estudio Demo\n  company = {COMPANY}\n  establishment = {ESTABLISHMENT}" in out
    assert "FUNCTIONAL TRAINING: lun 11:00" in out
    assert "PILATES: mié 19:30" in out
