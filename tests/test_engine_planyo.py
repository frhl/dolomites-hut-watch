"""Offline tests for hutwatch.engines.planyo (fixtures: tests/fixtures/planyo/README.md)."""

from __future__ import annotations

import datetime as dt
import pathlib
import unittest
from unittest import mock

from hutwatch.engines import planyo
from hutwatch.engines.base import Hut, Status
from hutwatch.http import USER_AGENT, FetchError, Response

FIX = pathlib.Path(__file__).parent / "fixtures" / "planyo"
TODAY = dt.date(2026, 11, 8)  # capture date of the fixtures

HUT = Hut(
    id="biella",
    name="Rifugio Biella (Seekofelhuette)",
    engine="planyo",
    booking_url="https://www.planyo.com/booking.php?calendar=67368&mode=resource_list&planyo_lang=EN",
    params={
        "site_id": 67368,
        "max_ahead_days": 365,
        "rooms": {
            "224735": ["Cima Nove", 6], "224733": ["Col de Lasta", 4],
            "224780": ["Croda del Becco", 2], "224728": ["Croda Rossa", 6],
            "224732": ["Pelmo", 6], "224734": ["Piccola Croda", 7],
            "224779": ["Sorapis", 8], "224729": ["Tofane", 8],
        },
    },
    phone="+39 349 2890550",
    email="info@rifugiobiella.com",
)


class FakeFetch:
    """Serves the search fixture for the ULAP POST and the calendar fixture for fetch-data GET."""

    def __init__(self, search: str, calendar: str | None = None):
        self.search, self.calendar, self.calls = search, calendar, []

    def __call__(self, method, url, *, params=None, data=None, json_body=None, headers=None, **kw):
        self.calls.append({"method": method, "url": url, "params": params, "data": data})
        if url == planyo.ULAP_URL:
            name, ctype = self.search, "text/plain; charset=UTF-8"
        elif url == planyo.FETCH_DATA_URL:
            if self.calendar is None:
                raise AssertionError("calendar feed should not be requested in this case")
            name, ctype = self.calendar, "application/json; charset=utf-8"
        else:
            raise AssertionError(f"unexpected URL {url}")
        return Response(status=200, url=url, headers={"Content-Type": ctype},
                        body=(FIX / name).read_bytes())


class PlanyoEngineTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(planyo, "_today", return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def run_check(self, night, search, calendar=None, guests=2):
        fake = FakeFetch(search, calendar)
        res = planyo.check(HUT, night, guests, fake)
        return res, fake

    def assert_search_request(self, call, start, end, guests=2):
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://www.planyo.com/Plugins/PlanyoFiles/non-planyo-ulap.php")
        d = call["data"]
        self.assertEqual(d["mode"], "resource_search")
        self.assertEqual(d["site_id"], "67368")
        self.assertEqual(d["quantity"], str(guests))      # exactly `guests` beds
        self.assertEqual(d["start_date"], start)            # check-in
        self.assertEqual(d["end_date"], end)                # check-out
        self.assertEqual(d["is_night"], "1")
        self.assertEqual(d["user_agent"], USER_AGENT)

    def assert_calendar_request(self, call, month, year):
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["url"], "https://www.planyo.com/fetch-data.php")
        self.assertEqual(call["params"], {"id": "67368", "month": str(month), "year": str(year), "grouped": "1"})

    # --- target night as captured -------------------------------------------------
    def test_target_night_full(self):
        res, fake = self.run_check(dt.date(2027, 6, 22), "search_target_20270622_q2.json", "fetchdata_2027_06.json")
        self.assertEqual(res.status, Status.FULL)
        self.assertIn("0 of 47 beds free", res.detail)
        self.assertEqual(len(fake.calls), 2)
        self.assert_search_request(fake.calls[0], "22.06.2027", "23.06.2027")
        self.assert_calendar_request(fake.calls[1], 6, 2027)

    def test_full_with_one_single_bed(self):
        # 19 June: calendar shows exactly 1 free bed (Cima Nove); reuse the real refusal body.
        res, _ = self.run_check(dt.date(2027, 6, 19), "search_target_20270622_q2.json", "fetchdata_2027_06.json")
        self.assertEqual(res.status, Status.FULL)
        self.assertIn("only 1 bed(s) free", res.detail)
        self.assertIn("Cima Nove: 1 free", res.detail)

    # --- available ----------------------------------------------------------------
    def test_available(self):
        res, fake = self.run_check(dt.date(2027, 6, 23), "search_available_20270623_q2.json")
        self.assertEqual(res.status, Status.AVAILABLE)
        self.assertIn("Pelmo", res.detail)
        self.assertNotIn("Croda Rossa", res.detail)  # only 1 bed there; quantity=2 excludes it
        self.assertEqual(res.options, ["Pelmo - 6 persone (resource 224732)"])
        self.assertEqual(len(fake.calls), 1)          # no calendar lookup needed
        self.assert_search_request(fake.calls[0], "23.06.2027", "24.06.2027")

    def test_available_ignores_links_for_other_dates(self):
        # Same real body, but asked for another night: the reserve links (23.06->24.06) must not count.
        res, _ = self.run_check(dt.date(2027, 6, 22), "search_available_20270623_q2.json", "fetchdata_2027_06.json")
        self.assertNotEqual(res.status, Status.AVAILABLE)

    def test_split_beds_across_rooms(self):
        res, fake = self.run_check(dt.date(2027, 6, 30), "search_split_20270630_q2.json", "fetchdata_2027_06.json")
        self.assertEqual(res.status, Status.AVAILABLE)
        self.assertIn("different rooms", res.detail)
        self.assertTrue(res.split)
        self.assertIn("Croda del Becco: 1 free", res.detail)
        self.assertIn("Sorapis: 1 free", res.detail)
        self.assert_search_request(fake.calls[0], "30.06.2027", "01.07.2027")

    # --- closed / not yet open ----------------------------------------------------
    def test_closed_out_of_season(self):
        res, fake = self.run_check(dt.date(2027, 6, 5), "search_closed_20270605_q2.json", "fetchdata_2027_06.json")
        self.assertEqual(res.status, Status.CLOSED)
        self.assertIn("closed", res.detail)
        self.assert_search_request(fake.calls[0], "05.06.2027", "06.06.2027")
        self.assert_calendar_request(fake.calls[1], 6, 2027)

    def test_booking_not_yet_open(self):
        res, fake = self.run_check(dt.date(2028, 6, 22), "search_notopen_20280622_q2.json", "fetchdata_2028_06.json")
        self.assertEqual(res.status, Status.CLOSED)
        self.assertIn("booking not yet open", res.detail)
        self.assert_search_request(fake.calls[0], "22.06.2028", "23.06.2028")
        self.assert_calendar_request(fake.calls[1], 6, 2028)

    # --- min stay -----------------------------------------------------------------
    def test_min_stay_like_refusal_is_unknown(self):
        # Planyo rooms here allow 1 night (min_rental_time 24 h), so no live min-stay refusal
        # exists. EDITED fixture: real "no results" body for a night where the calendar shows
        # Pelmo with 2 free beds. Search and calendar disagree -> UNKNOWN, not a guess.
        res, _ = self.run_check(dt.date(2027, 6, 23), "search_minstay_20270623_q2_EDITED.json",
                                "fetchdata_2027_06.json")
        self.assertEqual(res.status, Status.UNKNOWN)
        self.assertIn("min-stay", res.detail)
        self.assertIn("Pelmo: 2 free", res.detail)

    # --- errors -------------------------------------------------------------------
    def test_fetch_error_propagates(self):
        def boom(*a, **kw):
            raise FetchError("HTTP 503 from planyo")
        with self.assertRaises(FetchError):
            planyo.check(HUT, dt.date(2027, 6, 22), 2, boom)

    def test_calendar_fetch_error_propagates(self):
        fake = FakeFetch("search_target_20270622_q2.json", None)

        def fetch(method, url, **kw):
            if url == planyo.FETCH_DATA_URL:
                raise FetchError("timeout")
            return fake(method, url, **kw)
        with self.assertRaises(FetchError):
            planyo.check(HUT, dt.date(2027, 6, 22), 2, fetch)

    def test_unparseable_body_raises(self):
        def fetch(method, url, **kw):
            return Response(status=200, url=url, headers={"Content-Type": "text/html"},
                            body=b"<html>Incapsula incident</html>")
        with self.assertRaises(FetchError):
            planyo.check(HUT, dt.date(2027, 6, 22), 2, fetch)

    def test_wrong_calendar_month_raises(self):
        # 2028 feed returned for a 2027 night -> refuse to interpret
        with self.assertRaises(FetchError):
            self.run_check(dt.date(2027, 6, 22), "search_target_20270622_q2.json", "fetchdata_2028_06.json")


if __name__ == "__main__":
    unittest.main()
