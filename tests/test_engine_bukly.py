"""Offline tests for hutwatch.engines.bukly (Bukly / Inertia booking page).

Fixtures are raw /booking responses captured 2026-11-08 (one hash redacted, a few
EDITED copies for the stay-rule path); see tests/fixtures/bukly/README.md.
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from hutwatch.engines import bukly
from hutwatch.engines.base import Hut, Status
from hutwatch.http import FetchError, Response

FIX = Path(__file__).parent / "fixtures" / "bukly"

SCOTONI = Hut(id="scotoni", name="Rifugio Scotoni", engine="bukly",
              booking_url="https://scotoni.bukly.com/booking",
              params={"slug": "scotoni", "hotel_id": 4820})
COL_GALLINA = Hut(id="colgallina", name="Rifugio Col Gallina", engine="bukly",
                  booking_url="https://rifugiocolgallina.bukly.com/booking",
                  params={"slug": "rifugiocolgallina", "hotel_id": 4729})
AVERAU = Hut(id="averau", name="Rifugio Averau", engine="bukly",
             booking_url="https://rifugioaverau.bukly.com/booking",
             params={"slug": "rifugioaverau", "hotel_id": 3312})

TARGET = dt.date(2027, 6, 23)
D = dt.date


class FakeFetch:
    """Routes (checkin, checkout) -> fixture file (or Exception); records every call."""

    def __init__(self, routes: dict[tuple[str, str], str | bytes | Exception]):
        self.routes = routes
        self.calls: list[dict] = []

    def __call__(self, method, url, *, params=None, **kw):
        params = dict(params or {})
        self.calls.append({"method": method, "url": url, "params": params, **kw})
        target = self.routes.get((params.get("checkin"), params.get("checkout")))
        if target is None:
            raise AssertionError(f"unexpected request {method} {url} {params}")
        if isinstance(target, Exception):
            raise target
        body = target if isinstance(target, bytes) else (FIX / target).read_bytes()
        return Response(status=200, url=url, headers={"Content-Type": "text/html; charset=utf-8"},
                        body=body)


class RequestShape(unittest.TestCase):
    def assert_search(self, call, host, checkin, checkout, guests=2):
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["url"], f"https://{host}/booking")
        self.assertEqual(call["params"], {"rooms": str(guests), "checkin": checkin, "checkout": checkout})
        self.assertNotIn("data", call)
        self.assertNotIn("json_body", call)


class TestTargetNightFull(RequestShape):
    """23 Jun 2027, 2 guests: all three huts answered with no rooms (night in unavailableDates)."""

    def _run(self, hut, fixture, host):
        f = FakeFetch({("2027-06-23", "2027-06-24"): fixture})
        r = bukly.check(hut, TARGET, 2, f)
        self.assertEqual(r.status, Status.FULL, r.detail)
        self.assertEqual(len(f.calls), 1)
        self.assert_search(f.calls[0], host, "2027-06-23", "2027-06-24", guests=2)
        return r

    def test_scotoni(self):
        self._run(SCOTONI, "scotoni_2027-06-23_full.html", "scotoni.bukly.com")

    def test_col_gallina(self):
        self._run(COL_GALLINA, "colgallina_2027-06-23_full.html", "rifugiocolgallina.bukly.com")

    def test_averau(self):
        r = self._run(AVERAU, "averau_2027-06-23_full.html", "rifugioaverau.bukly.com")
        self.assertIn("unavailable", r.detail)


class TestAvailable(RequestShape):
    def test_col_gallina_18_jun(self):
        f = FakeFetch({("2027-06-18", "2027-06-19"): "colgallina_2027-06-18_available.html"})
        r = bukly.check(COL_GALLINA, D(2027, 6, 18), 2, f)
        self.assertEqual(r.status, Status.AVAILABLE, r.detail)
        self.assertEqual(len(f.calls), 1)
        self.assert_search(f.calls[0], "rifugiocolgallina.bukly.com", "2027-06-18", "2027-06-19")
        self.assertIn("Room 3: 3 beds €130/bed", r.detail)
        self.assertIn("Room 11: 1 room (sleeps 3) €570/room", r.detail)
        self.assertEqual(len(r.options), 4)


class TestTooFewBeds(unittest.TestCase):
    def test_one_bed_listed_for_two_guests_is_full(self):
        # The server lists a dorm with 1 free bed even for a 2-adult search.
        f = FakeFetch({("2027-07-20", "2027-07-21"): "scotoni_2027-07-20_onebed.html"})
        r = bukly.check(SCOTONI, D(2027, 7, 20), 2, f)
        self.assertEqual(r.status, Status.FULL, r.detail)
        self.assertIn("only 1 bed free for 2", r.detail)

    def test_one_bed_is_enough_for_one_guest(self):
        # Same response, judged for 1 guest (form echo says rooms=2, so call assess directly).
        f = FakeFetch({("2027-07-20", "2027-07-21"): "scotoni_2027-07-20_onebed.html"})
        s = bukly.search(SCOTONI, D(2027, 7, 20), D(2027, 7, 21), 2, f)
        ok, _ = bukly.assess(bukly.offers_for_night(s, D(2027, 7, 20)), 1)
        self.assertTrue(ok)


class TestClosed(unittest.TestCase):
    def test_beyond_booking_window(self):
        f = FakeFetch({("2027-12-01", "2027-12-02"): "colgallina_2027-12-01_beyond_window.html"})
        r = bukly.check(COL_GALLINA, D(2027, 12, 1), 2, f)
        self.assertEqual(r.status, Status.CLOSED, r.detail)
        self.assertIn("2027-11-09", r.detail)
        self.assertEqual(len(f.calls), 1)


class TestStayRule(RequestShape):
    """Bukly has no explicit min-stay message: a refused 1-night stay looks like 'no rooms'
    while the calendar lists the night as available. Fixtures marked EDITED (see README)."""

    ONE_NIGHT = ("2027-06-18", "2027-06-19")
    TWO_NIGHTS = ("2027-06-18", "2027-06-20")
    EARLIER = ("2027-06-17", "2027-06-19")

    def test_refused_then_read_from_two_night_window(self):
        f = FakeFetch({self.ONE_NIGHT: "colgallina_2027-06-18_EDITED_minstay_1night.html",
                       self.TWO_NIGHTS: "colgallina_2027-06-18_to_06-20_split.html"})
        r = bukly.check(COL_GALLINA, D(2027, 6, 18), 2, f)
        self.assertEqual(r.status, Status.AVAILABLE, r.detail)
        self.assertIn("2-night stay 2027-06-18->2027-06-20", r.detail)
        self.assertIn("split across rooms", r.detail)
        self.assertTrue(r.split)
        self.assertEqual(len(f.calls), 2)
        self.assert_search(f.calls[0], "rifugiocolgallina.bukly.com", *self.ONE_NIGHT)
        self.assert_search(f.calls[1], "rifugiocolgallina.bukly.com", *self.TWO_NIGHTS)

    def test_min_stay_refusal_everywhere(self):
        f = FakeFetch({self.ONE_NIGHT: "colgallina_2027-06-18_EDITED_minstay_1night.html",
                       self.TWO_NIGHTS: "colgallina_2027-06-18_to_06-20_EDITED_minstay.html",
                       self.EARLIER: "colgallina_2027-06-17_to_06-19_EDITED_minstay.html"})
        r = bukly.check(COL_GALLINA, D(2027, 6, 18), 2, f)
        self.assertEqual(r.status, Status.MIN_STAY, r.detail)
        self.assertEqual([c["params"]["checkin"] for c in f.calls],
                         ["2027-06-18", "2027-06-18", "2027-06-17"])
        for c in f.calls:
            self.assertEqual(c["params"]["rooms"], "2")

    def test_split_not_allowed(self):
        hut = Hut(**{**COL_GALLINA.__dict__, "params": {**COL_GALLINA.params, "allow_split": False}})
        f = FakeFetch({self.ONE_NIGHT: "colgallina_2027-06-18_EDITED_minstay_1night.html",
                       self.TWO_NIGHTS: "colgallina_2027-06-18_to_06-20_split.html",
                       self.EARLIER: "colgallina_2027-06-17_to_06-19_EDITED_minstay.html"})
        r = bukly.check(hut, D(2027, 6, 18), 2, f)
        self.assertEqual(r.status, Status.MIN_STAY, r.detail)
        self.assertIn("no single room for 2", r.detail)

    def test_window_budget_respected(self):
        hut = Hut(**{**COL_GALLINA.__dict__, "params": {**COL_GALLINA.params, "max_window_tries": 0}})
        f = FakeFetch({self.ONE_NIGHT: "colgallina_2027-06-18_EDITED_minstay_1night.html"})
        r = bukly.check(hut, D(2027, 6, 18), 2, f)
        self.assertEqual(r.status, Status.MIN_STAY)
        self.assertEqual(len(f.calls), 1)


class TestErrors(unittest.TestCase):
    def test_fetch_error_propagates(self):
        f = FakeFetch({("2027-06-23", "2027-06-24"): FetchError("HTTP 503 from bukly")})
        with self.assertRaises(FetchError):
            bukly.check(SCOTONI, TARGET, 2, f)

    def test_unparseable_body(self):
        f = FakeFetch({("2027-06-23", "2027-06-24"): b"<html><body>maintenance</body></html>"})
        with self.assertRaises(FetchError):
            bukly.check(SCOTONI, TARGET, 2, f)

    def test_error_page_component(self):
        body = (b'<script data-page="app" type="application/json">{"component":'
                b'"modules\\/Shared\\/resources\\/js\\/Pages\\/Error","props":{"status":404}}</script>')
        f = FakeFetch({("2027-06-23", "2027-06-24"): body})
        with self.assertRaises(FetchError):
            bukly.check(SCOTONI, TARGET, 2, f)

    def test_wrong_hotel(self):
        f = FakeFetch({("2027-06-23", "2027-06-24"): "colgallina_2027-06-23_full.html"})
        with self.assertRaises(FetchError):
            bukly.check(SCOTONI, TARGET, 2, f)  # Scotoni expects hotel_id 4820

    def test_answer_for_other_search_is_unknown(self):
        # The engine's form echo (dates, rooms) must match the request.
        f = FakeFetch({("2027-06-23", "2027-06-24"): "colgallina_2027-06-18_available.html"})
        self.assertEqual(bukly.check(COL_GALLINA, TARGET, 2, f).status, Status.UNKNOWN)
        f = FakeFetch({("2027-06-18", "2027-06-19"): "colgallina_2027-06-18_available.html"})
        self.assertEqual(bukly.check(COL_GALLINA, D(2027, 6, 18), 3, f).status, Status.UNKNOWN)
        self.assertEqual(f.calls[0]["params"]["rooms"], "3")

    def test_missing_params(self):
        with self.assertRaises(ValueError):
            bukly.check(Hut("x", "X", "bukly", "https://x"), TARGET, 2, FakeFetch({}))


class TestCalendar(unittest.TestCase):
    def test_calendar_nights(self):
        f = FakeFetch({("2027-06-18", "2027-06-19"): "colgallina_2027-06-18_available.html"})
        s = bukly.search(COL_GALLINA, D(2027, 6, 18), D(2027, 6, 19), 2, f)
        cal = bukly.calendar_nights(s, D(2027, 6, 11), D(2027, 6, 21))
        self.assertEqual(cal[D(2027, 6, 11)], (bukly.NIGHT_UNAVAILABLE, None))
        self.assertEqual(cal[D(2027, 6, 18)], (bukly.NIGHT_AVAILABLE, 130))
        self.assertEqual(cal[D(2027, 6, 20)][0], bukly.NIGHT_UNAVAILABLE)
        self.assertEqual(len(cal), 10)
        late = bukly.calendar_nights(s, D(2027, 11, 9), D(2027, 11, 11))
        self.assertEqual([v[0] for v in late.values()],
                         [bukly.NIGHT_UNAVAILABLE, bukly.NIGHT_NOT_ON_SALE])

    def test_fetch_calendar_one_request(self):
        # fetch_calendar searches start..start+1; the calendar in any /booking answer covers
        # the whole sellable window, so the 23 Jun capture stands in for the 1 Jun search.
        f = FakeFetch({("2027-06-01", "2027-06-02"): "scotoni_2027-06-23_full.html"})
        cal = bukly.fetch_calendar(SCOTONI, D(2027, 6, 1), D(2027, 7, 1), f, guests=2)
        avail = sorted(d.day for d, (state, _) in cal.items() if state == bukly.NIGHT_AVAILABLE)
        self.assertEqual(avail, [4, 5, 6, 7, 8, 9, 10, 11, 14, 18])
        self.assertEqual(len(f.calls), 1)


if __name__ == "__main__":
    unittest.main()
