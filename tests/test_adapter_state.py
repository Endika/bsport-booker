import datetime as dt
import json

import pytest

from bsport_booker.adapters.state import DailyMarker, JsonFileState
from bsport_booker.ports import StateError

NOW = dt.datetime(2026, 9, 26, 21, 0)


def test_a_missing_file_is_an_empty_state(tmp_path):
    assert JsonFileState(tmp_path / "state.json").load() == {}


def test_a_state_survives_a_round_trip_as_sorted_indented_json(tmp_path):
    path = tmp_path / "state.json"
    store = JsonFileState(path)

    assert store.save({"full:2": "2026-09-26", "booked:1": "2026-09-25"})

    assert store.load() == {"booked:1": "2026-09-25", "full:2": "2026-09-26"}
    assert path.read_text() == '{\n  "booked:1": "2026-09-25",\n  "full:2": "2026-09-26"\n}\n'
    assert not path.with_suffix(".tmp").exists()


def test_values_written_by_hand_are_read_as_text(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"booked:1": 20260926}))

    assert JsonFileState(path).load() == {"booked:1": "20260926"}


@pytest.mark.parametrize(("junk", "why"), [("{nope", "Expecting"), ("[]", "not a JSON object")])
def test_a_corrupt_state_raises(tmp_path, junk, why):
    path = tmp_path / "state.json"
    path.write_text(junk)

    with pytest.raises(StateError, match=why):
        JsonFileState(path).load()


def test_a_corrupt_state_is_set_aside_under_a_stamped_name(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{nope")

    assert JsonFileState(path).set_aside(NOW) == "state.json.corrupt-202609262100"

    assert not path.exists()
    assert (tmp_path / "state.json.corrupt-202609262100").read_text() == "{nope"


def test_a_state_that_cannot_be_moved_says_so(tmp_path):
    assert JsonFileState(tmp_path / "gone" / "state.json").set_aside(NOW) is None


def test_a_state_that_cannot_be_written_is_reported_not_raised(tmp_path, caplog):
    assert not JsonFileState(tmp_path / "missing" / "state.json").save({})

    assert "could not save state" in caplog.text


def test_the_daily_marker_opens_once_a_day(tmp_path):
    marker = DailyMarker(tmp_path)
    today = NOW.date()

    assert [marker.first_today(today), marker.first_today(today)] == [True, False]
    assert marker.first_today(today + dt.timedelta(days=1))


def test_a_marker_that_cannot_be_kept_lets_every_warning_through(tmp_path):
    marker = DailyMarker(tmp_path / "missing")

    assert marker.first_today(NOW.date())
    assert marker.first_today(NOW.date())
