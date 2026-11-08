"""Offline tests for hutwatch.engines.nuvolau (VikBooking; fixtures recorded 2026-11-08).

See tests/fixtures/nuvolau/README.md for the exact request behind each file and which
file is edited. Guests: VikBooking's availability calendar takes no guest count or
stay length (it is a per-night, per-bed-type table), so requests are asserted to carry
only the month, and the 2-guest threshold is shown to be applied locally (1 free bed ->
FULL for 2 but AVAILABLE for 1).
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from hutwatch.engines import nuvolau as engine
from hutwatch.engines.base import Hut, Status
from hutwatch.http import FetchError, Response

FIX = Path(__file__).parent / "fixtures" / "nuvolau"
FORM_URL = "https://rifugionuvolau.it/en/booking-form/"
AV_URL = "https://rifugionuvolau.it/en/availability/"
ROOM_IDS = [4, 6, 8, 5, 7]
HUT = Hut(
    id="nuvolau", name="Rifugio Nuvolau", engine="nuvolau", booking_url=FORM_URL,
    params={
        "form_url": FORM_URL, "availability_url": AV_URL, "room_ids": ROOM_IDS,
        "room_units": {"4": 3, "6": 4, "8": 4, "5": 5, "7": 8}, "probe_month": "2027-06",
    },
    phone="+39 0436 867938", email="info@rifugionuvolau.it",
)
JUN23, JUN24 = dt.date(2027, 6, 23), dt.date(2027, 6, 24)
TS_2027_06 = 1811808000  # option value of "June 2027" in the page's own month <select>
TS_2026_09 = 1788220800  # 2026-09-01T00:00Z


def resp(name: str | None = None, *, body: bytes | None = None, status: int = 200,
         url: str = FORM_URL) -> Response:
    return Response(status=status, url=url,
                    headers={"Content-Type": "text/html; charset=UTF-8"},
                    body=(FIX / name).read_bytes() if body is None else body)


FORM_OFF = lambda: resp("booking-form_en_disabled.html")          # noqa: E731  real Nuvolau
FORM_ON = lambda: resp("knaben_search-view_enabled.html")         # noqa: E731  real sibling
JUNE_CLOSED = lambda: resp("availability_2027-06.html", url=AV_URL)          # noqa: E731
JUNE_BEDS = lambda: resp("availability_2027-06_edited_beds.html", url=AV_URL)  # noqa: E731
SEPT_2026 = lambda: resp("availability_2026-09.html", url=AV_URL)            # noqa: E731


class FakeFetch:
    """Returns queued items in order; exceptions are raised. Fails if over-called."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        if not self.items:
            raise AssertionError(f"unexpected extra request: {method} {url} {kw}")
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def month_params(ts: int) -> dict:
    return {"view": "availability", "room_ids[0]": 4, "room_ids[1]": 6, "room_ids[2]": 8,
            "room_ids[3]": 5, "room_ids[4]": 7, "showtype": 2, "month": ts}


class RequestShape(unittest.TestCase):
    def assert_form_call(self, call):
        method, url, kw = call
        self.assertEqual((method, url), ("GET", FORM_URL))
        self.assertEqual(kw, {})  # plain page GET: no params, no body, nothing submitted

    def assert_month_call(self, call, ts):
        method, url, kw = call
        self.assertEqual((method, url), ("GET", AV_URL))
        self.assertEqual(kw, {"params": month_params(ts)})
        # no guest / date-range parameter exists in this calendar: guests applied locally
        self.assertFalse({"adults", "adults[]", "guests", "checkindate"} & set(kw["params"]))


class NotOpenLive(RequestShape):
    """Nuvolau as served on 2026-11-08: bookings disabled, June 2027 fully blocked."""

    def test_booking_open_false(self):
        f = FakeFetch(FORM_OFF(), JUNE_CLOSED())
        is_open, detail = engine.booking_open(HUT, f)
        self.assertFalse(is_open)
        self.assertIn("Rooms closed, see you in June 2027!", detail)
        self.assertIn("fully blocked", detail)
        self.assertEqual(len(f.calls), 2)
        self.assert_form_call(f.calls[0])
        self.assert_month_call(f.calls[1], TS_2027_06)

    def test_check_closed_both_nights(self):
        for night in (JUN23, JUN24):
            f = FakeFetch(FORM_OFF())
            r = engine.check(HUT, night, 2, f)
            self.assertEqual(r.status, Status.CLOSED, night)
            self.assertIn("Rooms closed", r.detail)
            self.assertEqual(len(f.calls), 1)  # calendar not fetched while disabled
            self.assert_form_call(f.calls[0])

    def test_parse_disabled_message_exact(self):
        st = engine.parse_form(FORM_OFF().text())
        self.assertEqual((st.enabled, st.message), (False, "Rooms closed, see you in June 2027!"))

    def test_june_2027_real_calendar_all_blocked(self):
        m = engine.parse_month(JUNE_CLOSED().text())
        self.assertEqual((m.year, m.month, len(m.nights())), (2027, 6, 30))
        self.assertEqual([r.id for r in m.rooms], ROOM_IDS)
        self.assertEqual(m.total_units, 24)  # = "The Rifugio has 24 beds"
        self.assertTrue(all(m.free_total(d) == 0 for d in m.nights()))

    def test_disabled_but_calendar_free_is_not_open(self):
        # closures lifted before the switch is flipped: still not bookable -> False
        is_open, detail = engine.booking_open(HUT, FakeFetch(FORM_OFF(), JUNE_BEDS()))
        self.assertFalse(is_open)
        self.assertIn("imminent", detail)
        self.assertIn("2027-06-23", detail)
        self.assertEqual(engine.check(HUT, JUN24, 2, FakeFetch(FORM_OFF())).status, Status.CLOSED)


class OpenButFull(RequestShape):
    """Booking form live (real VikBooking search view), June 2027 real all-blocked cells."""

    def test_booking_open_true_even_if_full(self):
        f = FakeFetch(FORM_ON(), JUNE_CLOSED())
        is_open, detail = engine.booking_open(HUT, f)
        self.assertTrue(is_open)
        self.assertIn("no free bed", detail)
        self.assert_form_call(f.calls[0])
        self.assert_month_call(f.calls[1], TS_2027_06)

    def test_check_full_both_nights(self):
        for night in (JUN23, JUN24):
            f = FakeFetch(FORM_ON(), JUNE_CLOSED())
            r = engine.check(HUT, night, 2, f)
            self.assertEqual(r.status, Status.FULL, night)
            self.assertIn("0/24", r.detail)
            self.assertEqual(len(f.calls), 2)
            self.assert_form_call(f.calls[0])
            self.assert_month_call(f.calls[1], TS_2027_06)

    def test_one_bed_is_full_for_two(self):
        r = engine.check(HUT, JUN23, 2, FakeFetch(FORM_ON(), JUNE_BEDS()))
        self.assertEqual(r.status, Status.FULL)
        self.assertIn("only 1/24", r.detail)
        # positive control for the local threshold: same answer, 1 guest -> AVAILABLE
        r1 = engine.check(HUT, JUN23, 1, FakeFetch(FORM_ON(), JUNE_BEDS()))
        self.assertEqual(r1.status, Status.AVAILABLE)


class OpenWithBeds(RequestShape):
    def test_check_available_24(self):
        f = FakeFetch(FORM_ON(), JUNE_BEDS())
        r = engine.check(HUT, JUN24, 2, f)
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertEqual(r.detail, "2/24 beds free: Bed in a shared 8-bed room: 2 free of 8")
        self.assert_month_call(f.calls[1], TS_2027_06)
        # 3 guests on the same answer -> FULL (threshold really is `guests`)
        self.assertEqual(engine.check(HUT, JUN24, 3, FakeFetch(FORM_ON(), JUNE_BEDS())).status,
                         Status.FULL)

    def test_booking_open_first_date(self):
        is_open, detail = engine.booking_open(HUT, FakeFetch(FORM_ON(), JUNE_BEDS()))
        self.assertTrue(is_open)
        self.assertIn("first bookable 2027 date seen: 2027-06-23 (1 beds)", detail)

    def test_fully_free_cell_without_span(self):
        # Template v1.8.15 renders a night with 0 bookings as an empty vbo-free-cell
        # (no data-units-*). Units then come from the room's other cells (8).
        old = ('<td class="vbo-occupied-cell vbo-partially-cell" data-cell-date="24/06/2027" '
               'data-cell-ts="1813795200"><span class="vbo-availability-day-container" '
               'data-units-booked="6" data-units-left="2">2</span></td>')
        new = '<td class="vbo-free-cell" data-cell-date="24/06/2027" data-cell-ts="1813795200"></td>'
        body = JUNE_BEDS().body.decode()
        self.assertEqual(body.count(old), 1)
        f = FakeFetch(FORM_ON(), resp(body=body.replace(old, new).encode(), url=AV_URL))
        r = engine.check(HUT, JUN24, 2, f)
        self.assertEqual((r.status, r.detail),
                         (Status.AVAILABLE, "8/24 beds free: Bed in a shared 8-bed room: 8 free of 8"))


class RealInSeasonData(RequestShape):
    """Nuvolau's own September 2026 calendar (real, unedited): partial cells."""

    def run_night(self, day, guests=2):
        f = FakeFetch(FORM_ON(), SEPT_2026())
        r = engine.check(HUT, dt.date(2026, 9, day), guests, f)
        self.assert_month_call(f.calls[1], TS_2026_09)
        return r

    def test_nights(self):
        self.assertEqual(self.run_night(15).status, Status.AVAILABLE)   # 5 in 8-bed room
        r2 = self.run_night(2)                                           # 1 + 1 in two dorms
        self.assertEqual(r2.status, Status.AVAILABLE)
        self.assertIn("Bed in a shared 4-bed room #8: 1 free of 4", r2.detail)
        self.assertEqual(self.run_night(3).status, Status.FULL)          # 1 bed
        self.assertEqual(self.run_night(3, guests=1).status, Status.AVAILABLE)
        self.assertEqual(self.run_night(20).status, Status.AVAILABLE)    # last open night
        self.assertEqual(self.run_night(21).status, Status.FULL)         # season over

    def test_units_two_ways(self):
        # beds per room from the cells (booked+left) must equal the configured room_units
        m = engine.parse_month(SEPT_2026().text(), room_units=None)
        self.assertEqual({str(r.id): r.units for r in m.rooms}, HUT.params["room_units"])
        # per-night total == sum of per-room data-units-left (aggregate vs per-record)
        for d in m.nights():
            self.assertEqual(m.free_total(d), sum(r.cells[d].left for r in m.rooms))


class Errors(unittest.TestCase):
    def test_fetch_error_first_request(self):
        with self.assertRaises(FetchError):
            engine.booking_open(HUT, FakeFetch(FetchError("HTTP 503 from x")))
        with self.assertRaises(FetchError):
            engine.check(HUT, JUN24, 2, FakeFetch(FetchError("timeout")))

    def test_http_500_response(self):
        bad = resp(body=b"oops", status=500)
        with self.assertRaises(FetchError):
            engine.booking_open(HUT, FakeFetch(bad))
        with self.assertRaises(FetchError):
            engine.check(HUT, JUN24, 2, FakeFetch(resp(body=b"oops", status=500)))

    def test_unrecognised_form_page(self):
        page = b"<html><body><h1>Just a moment...</h1></body></html>"  # e.g. a challenge page
        with self.assertRaises(FetchError):
            engine.booking_open(HUT, FakeFetch(resp(body=page)))
        with self.assertRaises(FetchError):
            engine.check(HUT, JUN24, 2, FakeFetch(resp(body=page)))

    def test_disabled_and_calendar_error_raises(self):
        with self.assertRaises(FetchError):
            engine.booking_open(HUT, FakeFetch(FORM_OFF(), FetchError("HTTP 502")))

    def test_open_and_calendar_error_still_true(self):
        is_open, detail = engine.booking_open(HUT, FakeFetch(FORM_ON(), FetchError("HTTP 502")))
        self.assertTrue(is_open)
        self.assertIn("calendar fetch failed", detail)

    def test_calendar_error_in_check_raises(self):
        with self.assertRaises(FetchError):
            engine.check(HUT, JUN24, 2, FakeFetch(FORM_ON(), FetchError("HTTP 502")))
        with self.assertRaises(FetchError):  # page without availability tables
            engine.check(HUT, JUN24, 2, FakeFetch(FORM_ON(), resp(body=b"<html></html>")))

    def test_wrong_month_returned(self):
        with self.assertRaises(FetchError):
            engine.check(HUT, JUN24, 2, FakeFetch(FORM_ON(), SEPT_2026()))

    def test_unknown_cell_class(self):
        old = ('<td class="vbo-occupied-cell" data-cell-date="24/06/2027" data-cell-ts="1813795200">'
               '<span class="vbo-availability-day-container" data-units-booked="5" '
               'data-units-left="0">0</span></td>')
        body = JUNE_CLOSED().body.decode()
        self.assertEqual(body.count(old), 1)  # room 5 (5-bed)
        body = body.replace(old, '<td class="vbo-weird-cell" data-cell-date="24/06/2027" '
                                 'data-cell-ts="1813795200"></td>')
        r = engine.check(HUT, JUN24, 2, FakeFetch(FORM_ON(), resp(body=body.encode(), url=AV_URL)))
        self.assertEqual(r.status, Status.UNKNOWN)


class Defaults(RequestShape):
    def test_empty_params_use_nuvolau_defaults(self):
        hut = Hut(id="nuvolau", name="Rifugio Nuvolau", engine="nuvolau",
                  booking_url="https://www.rifugionuvolau.it/en", params={})
        f = FakeFetch(FORM_OFF(), JUNE_CLOSED())
        self.assertFalse(engine.booking_open(hut, f)[0])
        self.assert_form_call(f.calls[0])
        self.assert_month_call(f.calls[1], TS_2027_06)

    def test_month_ts_matches_page_select(self):
        self.assertEqual(engine.month_ts(2027, 6), TS_2027_06)
        self.assertEqual(engine.month_ts(2026, 11), 1793491200)  # "November 2026" option


if __name__ == "__main__":
    unittest.main()
