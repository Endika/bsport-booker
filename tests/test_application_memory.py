import datetime as dt
from collections.abc import Iterable

import pytest

from bsport_booker.application.booking import Condition, Report
from bsport_booker.application.memory import FORGET_AFTER_DAYS, remember

TODAY = dt.date(2026, 9, 26)
YESTERDAY = "2026-09-25"


def run(state: dict[str, str], *, seen: Iterable[str] = (), news: Iterable[str] = ()) -> Report:
    report = Report(said=state)
    report.seen.update(seen)
    report.news.extend((key, "text") for key in news)
    return report


def test_a_condition_that_stopped_being_true_is_forgotten_so_it_can_be_said_again():
    state = {"full:1": YESTERDAY, "nocredits:2": YESTERDAY}

    after = remember(state, run(state, seen={"nocredits:2"}), TODAY, announced=True)

    assert after == {"nocredits:2": "2026-09-26"}


def test_what_is_not_a_condition_is_kept_while_it_is_recent():
    state = {"booked:1": YESTERDAY, "fatal:2026-09-25:BsportError:0": YESTERDAY}

    assert remember(state, run(state), TODAY, announced=True) == state


def test_news_is_only_remembered_once_it_was_announced():
    fresh = run({}, seen={"full:1"}, news={"full:1", "booked:2"})

    assert remember({}, fresh, TODAY, announced=False) == {}
    assert remember({}, fresh, TODAY, announced=True) == {
        "full:1": "2026-09-26",
        "booked:2": "2026-09-26",
    }


def test_anything_older_than_the_cutoff_is_pruned():
    edge = (TODAY - dt.timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    older = (TODAY - dt.timedelta(days=FORGET_AFTER_DAYS + 1)).isoformat()
    state = {"booked:1": edge, "booked:2": older}

    assert remember(state, run(state), TODAY, announced=True) == {"booked:1": edge}


@pytest.mark.parametrize("condition", list(Condition))
def test_every_kind_of_condition_is_forgotten_once_it_is_no_longer_seen(condition):
    key = condition.key(1)
    state = {key: YESTERDAY}

    assert remember(state, run(state), TODAY, announced=True) == {}
    assert remember(state, run(state, seen={key}), TODAY, announced=True) == {key: "2026-09-26"}


def test_condition_keys_keep_the_shape_of_existing_state_files():
    assert Condition.NO_PACK.key() == "nopack:"
    assert Condition.ERROR.key(12, 400) == "error:12:400"
