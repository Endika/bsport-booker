from __future__ import annotations

import datetime as dt
import tempfile
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
    bsport.offer("2026-10-24T09:00")  # yours, but on a day you don't book
    bsport.offer("2026-11-25T10:00", "ENTRENAMIENTO PERSONAL")  # someone else's, far ahead

    assert tick(home, bsport, "--status") == 0

    assert booked_offers(bsport) == []
    [message] = slack(bsport)
    assert "✅ lun 28/09 11:00 Functional Training: reservada" in message
    assert "⚠️ mié 07/10 11:00 Functional Training: sin créditos para ese día" in message
    assert "➕ mié 21/10 11:00 Functional Training: la reservaría" in message
    assert "Tus clases están publicadas hasta el sáb 24/10" in message


def test_every_page_of_offers_is_read(home, bsport):
    bsport.pack(*OCTOBER, credits=12)
    bsport.page_size = 2
    for day in ("09", "14", "16", "19", "21"):
        bsport.offer(f"2026-10-{day}T11:00")

    tick(home, bsport)

    assert len(booked_offers(bsport)) == 5


@pytest.mark.parametrize("junk", ["{nope", "[]"])
def test_a_corrupt_state_is_set_aside_once_and_booking_goes_on(home, bsport, junk):
    bsport.pack(*SEPTEMBER, credits=5)
    monday = bsport.offer("2026-09-28T11:00")
    (home / "state.json").write_text(junk)

    assert tick(home, bsport) == 0
    tick(home, bsport)

    assert booked_offers(bsport) == [monday["id"]]
    assert sum("corrupto" in m for m in slack(bsport)) == 1
    assert [p.name for p in home.glob("state.json.corrupt-*")] == [
        "state.json.corrupt-202609262100"
    ]


def test_a_state_that_cannot_be_saved_speaks_once_a_day(home, bsport, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    config = home / "config.toml"
    config.write_text('state = "missing/dir/state.json"\n' + config.read_text())
    bsport.pack(*SEPTEMBER, credits=5)
    bsport.offer("2026-09-30T11:00", full=True)

    for minutes in range(0, 180, 30):
        tick(home, bsport, now=NOW.replace(day=27, hour=0) + dt.timedelta(minutes=minutes))
    tick(home, bsport, now=NOW.replace(day=28, hour=0))

    messages = slack(bsport)
    assert len(messages) == 2
    assert all("no puedo guardar" in m and "está llena" in m for m in messages)


def test_news_that_slack_did_not_take_is_sent_again_next_run(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    bsport.offer("2026-09-28T11:00")
    bsport.slack_ok = False

    assert tick(home, bsport) == 1
    bsport.slack_ok = True
    assert tick(home, bsport) == 0

    assert "🎉 lun 28/09 11:00 Functional Training: reservada" in slack(bsport)[-1]
    assert len(booked_offers(bsport)) == 1


def test_missing_credentials_reach_slack_once_a_day(home, bsport):
    (home / "credentials").unlink()

    assert tick(home, bsport) == 1
    assert tick(home, bsport) == 1

    assert len(slack(bsport)) == 1
    assert "credentials" in slack(bsport)[0]
    assert [c for c in bsport.calls if c[1] != "slack"] == []


def test_a_class_that_fills_again_after_freeing_up_is_announced_again(home, bsport):
    bsport.pack(*SEPTEMBER, credits=0)
    bsport.pack(*OCTOBER, credits=12)
    wednesday = bsport.offer("2026-09-30T11:00", full=True)

    tick(home, bsport)
    wednesday["full"] = False  # frees up, but there are no credits for that day
    tick(home, bsport)
    wednesday["full"] = True
    tick(home, bsport)

    assert sum("está llena" in m for m in slack(bsport)) == 2


def test_odd_shapes_from_bsport_still_book(home, bsport):
    unlimited = bsport.pack(*SEPTEMBER, credits=0)
    unlimited["available_credits"] = None
    utc = bsport.offer("2026-09-28T11:00", credits=1)
    utc["date_start"] = "2026-09-28T09:00:00Z"
    utc["timezone_name"] = "Europe/Madrid"
    utc["credit_price"] = "1.00"

    assert tick(home, bsport) == 0

    assert booked_offers(bsport) == [utc["id"]]
    assert "Créditos: ilimitados (bono 09/09–08/10)" in slack(bsport)[0]


def test_winter_time_classes_match_the_same_wall_clock_hour(home, bsport):
    bsport.pack("2026-10-20", "2026-11-19", credits=5)
    after_the_change = bsport.offer("2026-10-26T11:00")
    after_the_change["date_start"] = "2026-10-26T11:00:00+01:00"

    tick(home, bsport)

    assert booked_offers(bsport) == [after_the_change["id"]]


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


def test_offers_on_a_second_page_behind_links_next_are_booked(home, bsport):
    bsport.pack(*OCTOBER, credits=12)
    bsport.page_size = 2
    for day in ("09", "14", "16", "19", "21", "23"):
        bsport.offer(f"2026-10-{day}T11:00")

    tick(home, bsport)

    assert len(booked_offers(bsport)) == 6
    assert "vie 23/10" in slack(bsport)[0]


def test_a_list_shorter_than_its_count_is_an_error_not_a_quiet_cut(home, bsport):
    bsport.pack(*OCTOBER, credits=12)
    bsport.page_size = 2
    bsport.hide_next = True
    for day in ("09", "14", "16"):
        bsport.offer(f"2026-10-{day}T11:00")

    assert tick(home, bsport) == 1

    assert booked_offers(bsport) == []
    assert "read 2 of 3" in slack(bsport)[0]


def test_a_failure_with_no_message_is_named_by_its_type(home, bsport, monkeypatch):
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError

    real = bsport.request
    monkeypatch.setattr(
        bsport,
        "request",
        lambda method, url, **kw: broken() if "/book/v1/offer/" in url else real(method, url, **kw),
    )

    assert tick(home, bsport) == 1

    assert slack(bsport)[0].endswith("no he podido mirar las clases. RuntimeError")


@pytest.mark.parametrize("mode", ["--dry-run", "--status"])
def test_a_look_never_promises_more_than_the_packs_pay_and_shows_the_real_balance(
    home, bsport, capsys, mode
):
    bsport.pack(*SEPTEMBER, credits=1)
    bsport.offer("2026-09-28T11:00")
    bsport.offer("2026-09-30T11:00")

    tick(home, bsport, mode)

    out = capsys.readouterr().out
    assert "➕ lun 28/09 11:00 Functional Training: la reservaría" in out
    assert "⚠️ mié 30/09 11:00 Functional Training: sin créditos para ese día" in out
    assert "Créditos: 1 (bono 09/09–08/10)" in out
    assert booked_offers(bsport) == []


def test_discover_shows_class_times_on_the_studio_wall_clock(home, bsport, capsys):
    utc = bsport.offer("2026-09-28T11:00")
    utc["date_start"] = "2026-09-28T09:00:00Z"
    utc["timezone_name"] = "Europe/Madrid"
    bsport.bookings.append(utc["id"])
    bsport.studio = {"id": ESTABLISHMENT, "title": "Estudio Demo"}

    assert tick(home, bsport, "--discover") == 0

    assert "FUNCTIONAL TRAINING: lun 11:00" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["--status", "--dry-run", "--discover"])
def test_a_look_reports_a_corrupt_state_and_leaves_it_where_it_is(home, bsport, capsys, mode):
    bsport.pack(*SEPTEMBER, credits=5)
    monday = bsport.offer("2026-09-28T11:00")
    bsport.bookings.append(monday["id"])
    bsport.studio = {"id": ESTABLISHMENT, "title": "Estudio Demo"}
    (home / "state.json").write_text("{nope")

    assert tick(home, bsport, mode) == 0

    assert "corrupto" in capsys.readouterr().out
    assert (home / "state.json").read_text() == "{nope"
    assert list(home.glob("state.json.corrupt-*")) == []
    assert sum("corrupto" in m for m in slack(bsport)) == (1 if mode == "--status" else 0)


def test_the_next_real_run_after_a_look_still_sets_a_corrupt_state_aside_and_says_so(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    (home / "state.json").write_text("{nope")

    tick(home, bsport, "--status")
    tick(home, bsport)

    assert [p.name for p in home.glob("state.json.corrupt-*")] == [
        "state.json.corrupt-202609262100"
    ]
    assert "lo he apartado" in slack(bsport)[-1]


def test_a_redirected_booking_is_an_error_and_is_never_reported_as_booked(home, bsport):
    bsport.pack(*SEPTEMBER, credits=5)
    bsport.offer("2026-09-28T11:00")
    bsport.book_status = 302

    assert tick(home, bsport) == 1

    [message] = slack(bsport)
    assert "no he podido reservarla (book: HTTP 302" in message
    assert "reservada" not in message
