import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bsport_booker.adapters.bsport.http import BsportGateway
from bsport_booker.adapters.state import DailyMarker, JsonFileState
from bsport_booker.application.tick import Mode, Tick
from bsport_booker.config import Config
from bsport_booker.domain.models import Wanted

from .fakes import COMPANY, ESTABLISHMENT, FakeBsport, Recorder

NOW = dt.datetime(2026, 9, 26, 21, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def dry_run(tmp_path: Path, bsport: FakeBsport, notifier: Recorder) -> Tick:
    config = Config(
        company=COMPANY,
        establishment=ESTABLISHMENT,
        classes=(Wanted("Functional training", frozenset({0}), dt.time(11)),),
        horizon_days=60,
        low_credits=2,
        credentials=tmp_path / "credentials",
        state=tmp_path / "state.json",
        slack_token="xoxb-1",
        slack_channel="C1",
    )
    return Tick(
        mode=Mode.DRY_RUN,
        bsport=BsportGateway(bsport, lambda: (bsport.email, "s3cret")),
        notifier=notifier,
        store=JsonFileState(config.state),
        unsaved_gate=DailyMarker(tmp_path),
        config=config,
        now=NOW,
    )


@pytest.mark.parametrize("password_changed", [False, True])
def test_a_dry_run_tells_nobody_even_with_a_notifier_wired_in(tmp_path, password_changed):
    bsport = FakeBsport()
    bsport.pack("2026-09-09", "2026-10-08", credits=5)
    bsport.offer("2026-09-28T11:00")
    if password_changed:
        bsport.password = "changed"
    notifier = Recorder()

    outcome = dry_run(tmp_path, bsport, notifier).run()

    assert outcome.ok is not password_changed
    assert outcome.text
    assert notifier.sent == []
    assert bsport.posted("register_booking") == []
    assert not (tmp_path / "state.json").exists()
