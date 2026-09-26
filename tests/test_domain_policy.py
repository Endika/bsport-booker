import datetime as dt
from dataclasses import replace
from zoneinfo import ZoneInfo

from bsport_booker.domain import (
    Book,
    Offer,
    Pack,
    Reason,
    Skip,
    Wanted,
    decide,
    due,
    in_force,
    pay_with,
    published_until,
    spend,
)

MADRID = ZoneInfo("Europe/Madrid")
NOW = dt.datetime(2026, 9, 26, 21, 0, tzinfo=MADRID)  # a Saturday
MON_WED_AT_11 = (Wanted("Functional training", frozenset({0, 2}), dt.time(11, 0)),)


def offer(
    when: str, name: str = "FUNCTIONAL TRAINING", *, id: int = 1, available: bool = True,
    full: bool = False, credits: int = 1,
) -> Offer:  # fmt: skip
    start = dt.datetime.fromisoformat(when).replace(tzinfo=MADRID)
    return Offer(id, name, start, available, full, credits)


def pack(
    start: str, end: str, credits: int | None, *, id: int = 10, disabled: bool = False
) -> Pack:
    return Pack(id, dt.date.fromisoformat(start), dt.date.fromisoformat(end), credits, disabled)


SEPTEMBER = pack("2026-09-09", "2026-10-08", 3)
AUTUMN = ("2026-09-01", "2026-12-31")
MONDAY = offer("2026-09-28T11:00")


def test_due_keeps_the_wanted_day_hour_and_name_soonest_first():
    wednesday = offer("2026-09-30T11:00", id=2)
    monday = offer("2026-09-28T11:00", id=1)
    others = [
        offer("2026-09-29T11:00", id=3),  # a Tuesday
        offer("2026-09-30T12:00", id=4),  # the wrong hour
        offer("2026-09-30T11:00", "PILATES", id=5),
    ]

    assert due([wednesday, *others, monday], MON_WED_AT_11, NOW) == [monday, wednesday]


def test_due_ignores_accents_and_case_in_the_class_name():
    accented = offer("2026-09-28T11:00", "FÚNCTIONAL TRAINING ")
    assert due([accented], MON_WED_AT_11, NOW) == [accented]


def test_due_drops_a_class_that_has_started():
    started = MONDAY
    assert due([started], MON_WED_AT_11, started.start) == []


def test_due_matches_the_studio_wall_clock_across_the_change_to_winter_time():
    stamp = dt.datetime.fromisoformat("2026-10-26T11:00+01:00")
    after_the_change = replace(offer("2026-10-26T11:00"), start=stamp)
    assert due([after_the_change], MON_WED_AT_11, NOW) == [after_the_change]


def test_a_booked_class_is_skipped_before_anything_else_is_looked_at():
    full_and_booked = offer("2026-09-28T11:00", full=True, available=False)

    assert decide(full_and_booked, [SEPTEMBER], {1}) == Skip(full_and_booked, Reason.BOOKED)


def test_unavailable_is_said_before_full():
    both = offer("2026-09-28T11:00", full=True, available=False)
    assert decide(both, [SEPTEMBER], set()) == Skip(both, Reason.UNAVAILABLE)


def test_a_full_class_is_skipped():
    full = offer("2026-09-28T11:00", full=True)
    assert decide(full, [SEPTEMBER], set()) == Skip(full, Reason.FULL)


def test_an_open_class_is_booked_with_a_pack_that_covers_its_day():
    monday = offer("2026-09-28T11:00")
    assert decide(monday, [SEPTEMBER], set()) == Book(monday, SEPTEMBER)


def test_a_full_pack_for_next_month_cannot_pay_for_this_month():
    empty = pack("2026-09-09", "2026-10-08", 0, id=1)
    october = pack("2026-10-09", "2026-11-08", 12, id=2)
    wednesday = offer("2026-10-07T11:00")

    assert decide(wednesday, [empty, october], set()) == Skip(wednesday, Reason.NO_CREDITS)


def test_the_pack_that_expires_first_pays():
    late = pack("2026-09-01", "2026-12-31", 10, id=1)
    soon = pack("2026-09-20", "2026-10-01", 10, id=2)
    assert pay_with([late, soon], MONDAY) == soon


def test_a_disabled_pack_never_pays():
    assert pay_with([pack(*AUTUMN, 10, disabled=True)], MONDAY) is None


def test_a_pack_short_of_the_price_does_not_pay():
    assert pay_with([pack(*AUTUMN, 1)], offer("2026-09-28T11:00", credits=2)) is None


def test_even_a_free_class_needs_a_pack_with_credits_left():
    assert pay_with([pack(*AUTUMN, 0)], offer("2026-09-28T11:00", credits=0)) is None


def test_an_unlimited_pack_always_pays():
    unlimited = pack(*AUTUMN, None)
    assert pay_with([unlimited], offer("2026-09-28T11:00", credits=5)) == unlimited


def test_spending_takes_the_price_from_that_pack_only():
    other = pack("2026-10-09", "2026-11-08", 12, id=20)
    monday = offer("2026-09-28T11:00", credits=2)

    after = spend([SEPTEMBER, other], Book(monday, SEPTEMBER))

    assert [p.credits for p in after] == [1, 12]


def test_spending_from_an_unlimited_pack_changes_nothing():
    unlimited = pack(*AUTUMN, None)
    assert spend([unlimited], Book(MONDAY, unlimited)) == [unlimited]


def test_what_is_spent_in_a_run_is_not_there_for_the_next_class():
    one_left = pack("2026-09-09", "2026-10-08", 1)
    monday, wednesday = offer("2026-09-28T11:00", id=1), offer("2026-09-30T11:00", id=2)

    first = decide(monday, [one_left], set())
    assert isinstance(first, Book)
    packs = spend([one_left], first)

    assert decide(wednesday, packs, {monday.id}) == Skip(wednesday, Reason.NO_CREDITS)


def test_packs_in_force_leave_out_expired_and_disabled_ones_oldest_first():
    october = pack("2026-10-09", "2026-11-08", 12, id=2)
    expired = pack("2026-08-09", "2026-09-08", 4, id=3)
    disabled = pack("2026-09-01", "2026-12-31", 4, id=4, disabled=True)

    assert in_force([october, expired, disabled, SEPTEMBER], NOW.date()) == [SEPTEMBER, october]


def test_published_until_counts_your_classes_at_any_day_or_hour_and_nobody_else_s():
    saturday = offer("2026-10-24T09:00")
    others = offer("2026-11-25T10:00", "ENTRENAMIENTO PERSONAL")

    assert published_until([offer("2026-10-21T11:00"), saturday, others], MON_WED_AT_11) == (
        saturday.start
    )


def test_published_until_is_none_when_none_of_yours_is_out():
    assert published_until([offer("2026-10-21T11:00", "PILATES")], MON_WED_AT_11) is None
