import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from bsport_booker.adapters.bsport import BsportGateway, parsing
from bsport_booker.adapters.bsport.http import API, LOGIN, MAX_PAGES
from bsport_booker.ports import BsportError, Response

from .fakes import COMPANY, ESTABLISHMENT, FakeBsport, Scripted, Unreachable, json_response

MADRID = ZoneInfo("Europe/Madrid")
MEMBER = f"{API}/core-data/v1/member/?me=true"
OCTOBER = (dt.date(2026, 10, 1), dt.date(2026, 10, 31))


def logged_in(transport: FakeBsport | Scripted) -> BsportGateway:
    gateway = BsportGateway(transport)
    gateway.login("me@example.org", "s3cret")
    return gateway


def scripted(**pages: Response) -> Scripted:
    return Scripted({LOGIN: json_response({"token": "tok-abc"}), **pages})


def test_a_utc_start_lands_on_the_studio_wall_clock():
    start = parsing.local_start("2026-09-28T09:00:00Z", "Europe/Madrid")

    assert (start.hour, start.utcoffset()) == (11, dt.timedelta(hours=2))


def test_a_start_with_no_offset_is_read_in_the_studio_zone_or_madrid():
    canary = parsing.local_start("2026-09-28T11:00:00", "Atlantic/Canary")
    unnamed = parsing.local_start("2026-09-28T11:00:00", None)

    assert canary.tzinfo == ZoneInfo("Atlantic/Canary")
    assert unnamed.tzinfo == MADRID
    assert canary.hour == unnamed.hour == 11


@pytest.mark.parametrize("zone", ["Mars/Olympus", "", None])
def test_an_unknown_zone_keeps_the_offset_bsport_wrote(zone):
    start = parsing.local_start("2026-10-26T11:00:00+01:00", zone)

    assert (start.hour, start.utcoffset()) == (11, dt.timedelta(hours=1))


def test_offers_read_prices_as_decimals_and_missing_fields_as_no():
    [offer] = parsing.offers(
        [{"id": "7", "date_start": "2026-09-28T11:00:00+02:00", "credit_price": "1.00"}]
    )

    assert (offer.id, offer.name, offer.credits) == (7, "", 1)
    assert not offer.available
    assert not offer.full


def test_a_free_offer_costs_nothing():
    [offer] = parsing.offers(
        [{"id": 1, "date_start": "2026-09-28T11:00:00+02:00", "credit_price": None}]
    )

    assert offer.credits == 0


def test_packs_without_dates_are_dropped_and_a_missing_count_means_unlimited():
    rows: list[dict[str, Any]] = [
        {
            "id": 1,
            "starting_date": "2026-09-09",
            "ending_date": "2026-10-08",
            "available_credits": None,
        },
        {
            "id": 2,
            "starting_date": "2026-10-09",
            "ending_date": "2026-11-08",
            "available_credits": "3.0",
        },
        {"id": 3, "starting_date": None, "ending_date": "2026-11-08", "available_credits": 5},
    ]

    assert [(p.id, p.credits) for p in parsing.packs(rows)] == [(1, None), (2, 3)]


def test_only_live_bookings_count_as_booked():
    rows = [{"offer": {"id": 1}, "status": True}, {"offer": {"id": 2}, "status": False}]

    assert parsing.booked(rows) == {1}


def test_studios_come_from_bookings_that_name_one():
    rows: list[dict[str, Any]] = [
        {"offer": {"activity": {"etablissement": {"id": 5678, "title": "Estudio Demo"}}}},
        {"offer": {"activity": {"etablissement": None}}},
        {"offer": None},
    ]

    assert parsing.studios(rows) == {5678: "Estudio Demo"}


def test_listings_leave_a_missing_company_and_activity_blank():
    [listing] = parsing.listings([{"date_start": "2026-09-28T11:00:00+02:00"}])

    assert (listing.company, listing.activity) == ("", "")


def test_listings_are_on_the_studio_wall_clock_like_offers():
    [listing] = parsing.listings(
        [{"date_start": "2026-09-28T09:00:00Z", "timezone_name": "Europe/Madrid"}]
    )

    assert (listing.start.hour, listing.start.utcoffset()) == (11, dt.timedelta(hours=2))


def test_the_detail_of_an_error_that_is_not_json_is_its_first_120_characters():
    assert parsing.detail(Response(502, b"  <html>" + b"x" * 200)) == "<html>" + "x" * 112


def test_offers_on_every_page_behind_links_next_are_read():
    bsport = FakeBsport(page_size=2)
    for day in range(1, 8):
        bsport.offer(f"2026-10-{day:02d}T11:00")

    offers = logged_in(bsport).offers(COMPANY, ESTABLISHMENT, *OCTOBER)

    assert len(offers) == 7
    assert sum(1 for _, path, _ in bsport.calls if path == "/book/v1/offer/") == 4


def test_bookings_on_every_page_behind_a_top_level_next_are_read():
    bsport = FakeBsport(page_size=2, bookings=[1, 2, 3, 4, 5])

    assert logged_in(bsport).booked_offers() == {1, 2, 3, 4, 5}


def test_a_list_shorter_than_its_count_raises():
    bsport = FakeBsport(page_size=2, hide_next=True)
    for day in (9, 14, 16):
        bsport.offer(f"2026-10-{day:02d}T11:00")

    with pytest.raises(BsportError, match="read 2 of 3 and found no next page"):
        logged_in(bsport).offers(COMPANY, ESTABLISHMENT, *OCTOBER)


def test_an_unpaginated_list_is_taken_whole():
    bsport = FakeBsport()
    bsport.pack("2026-09-09", "2026-10-08", credits=3)
    bsport.pack("2026-10-09", "2026-11-08", credits=12)

    assert [p.credits for p in logged_in(bsport).packs(7)] == [3, 12]


def test_pages_that_never_end_are_cut_off():
    endless = scripted(**{MEMBER: json_response({"results": [], "next": MEMBER})})

    with pytest.raises(BsportError, match=f"more than {MAX_PAGES} pages"):
        logged_in(endless).member_id()


@pytest.mark.parametrize("page", [{"results": None}, "a string"])
def test_a_page_of_an_unexpected_shape_raises(page):
    with pytest.raises(BsportError, match="unexpected shape"):
        logged_in(scripted(**{MEMBER: json_response(page)})).member_id()


def test_a_body_that_is_not_json_raises_with_its_start():
    garbled = scripted(**{MEMBER: Response(200, b"<html>maintenance</html>")})

    with pytest.raises(BsportError, match="not JSON: '<html>maintenance"):
        logged_in(garbled).member_id()


def test_an_http_error_carries_its_status_and_what_bsport_said():
    refused = scripted(**{MEMBER: json_response({"detail": "nope"}, 403)})

    with pytest.raises(BsportError) as caught:
        logged_in(refused).member_id()

    assert str(caught.value) == 'member: HTTP 403 {"detail": "nope"}'
    assert caught.value.status == 403


def test_a_network_failure_is_a_bsport_error_with_status_zero():
    with pytest.raises(BsportError, match="login: HTTP 0 network: timed out") as caught:
        BsportGateway(Unreachable()).login("me@example.org", "s3cret")

    assert caught.value.status == 0


def test_a_login_answer_without_a_token_raises():
    with pytest.raises(BsportError, match="no token"):
        BsportGateway(Scripted({LOGIN: json_response({"detail": "ok"})})).login("a", "b")


def test_every_call_after_login_carries_the_token():
    transport = scripted(**{MEMBER: json_response({"results": [{"id": 7}]})})

    assert logged_in(transport).member_id() == 7

    _, _, headers, _ = transport.requests[-1]
    assert headers["Authorization"] == "Token tok-abc"


def test_more_than_one_member_is_refused():
    two = scripted(**{MEMBER: json_response({"results": [{"id": 7}, {"id": 8}]})})

    with pytest.raises(BsportError, match="expected one member, got 2"):
        logged_in(two).member_id()
