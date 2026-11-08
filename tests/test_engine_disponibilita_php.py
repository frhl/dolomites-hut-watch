"""Offline tests for hutwatch.engines.disponibilita_php (fixtures recorded 2026-11-08).

See tests/fixtures/disponibilita_php/README.md for the exact request behind each file.

Min-stay: this engine has none. The calendar is a per-night bed table with no
guest count and no stay length, so it never refuses a 1-night query; MIN_STAY
cannot occur and there is no min-stay fixture.
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path
from unittest import mock

from hutwatch.engines import disponibilita_php as engine
from hutwatch.engines.base import Hut, Status
from hutwatch.http import FetchError, Response

FIX = Path(__file__).parent / "fixtures" / "disponibilita_php"
LAGAZUOI_URL = "https://rifugiolagazuoi.com/EN/disponibilita.php"
TISSI_URL = "https://www.rifugiotissi.com/EN/disponibilita.php"

LAGAZUOI = Hut(
    id="lagazuoi", name="Rifugio Lagazuoi", engine="disponibilita_php",
    booking_url=LAGAZUOI_URL, params={"url": LAGAZUOI_URL},
)
TISSI = Hut(
    id="tissi", name="Rifugio Tissi", engine="disponibilita_php",
    booking_url=TISSI_URL, params={"url": TISSI_URL},
)
TODAY = dt.date(2026, 11, 8)  # day the fixtures were recorded


def fixture_response(name: str, url: str, status: int = 200, body: bytes | None = None) -> Response:
    return Response(
        status=status, url=url,
        headers={"Content-Type": "text/html; charset=UTF-8"},
        body=(FIX / name).read_bytes() if body is None else body,
    )


class FakeFetch:
    """Returns queued items in order (last one repeats); exceptions are raised."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item


class DisponibilitaPhpTest(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(engine, "_today", return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def june(self, hut=LAGAZUOI, name="lagazuoi_2027-06.html"):
        return FakeFetch(fixture_response(name, hut.params["url"] + "?prm=17&chm=1"))

    def assert_june_2027_request(self, fetch, url=LAGAZUOI_URL):
        self.assertEqual(len(fetch.calls), 1)
        method, called_url, kw = fetch.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(called_url, url)
        # June 2027 = month index 18 from Jan 2026; sent like the page's own
        # "next month" arrow from May 2027. The calendar takes no guest count
        # (guests are applied locally), so only prm/chm are sent.
        self.assertEqual(kw.get("params"), {"prm": 17, "chm": 1})
        self.assertNotIn("data", kw)

    # --- target night: Lagazuoi 23 Jun 2027 is grey -> FULL -------------------
    def test_full_target_night(self):
        fetch = self.june()
        r = engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)
        self.assertEqual(r.status, Status.FULL)
        self.assertIn("not available", r.detail)
        self.assertIn("June 2027: 7-10", r.detail)
        self.assert_june_2027_request(fetch)

    # --- available -------------------------------------------------------------
    def test_available_dorm_only(self):
        fetch = self.june()
        r = engine.check(LAGAZUOI, dt.date(2027, 6, 8), 2, fetch)
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertEqual(r.options, ["Dormitories with bunk beds: 16 beds"])
        self.assertTrue(r.detail.startswith("16 places free"))
        self.assertFalse(r.split)  # one dorm type holds both beds
        self.assert_june_2027_request(fetch)

    def test_available_room_and_dorm(self):
        r = engine.check(LAGAZUOI, dt.date(2027, 6, 9), 2, self.june())
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertEqual(r.options, [
            "1x Quadruple room with 1 pull down wall bed (max 4 pers.)",
            "Dormitories with bunk beds: 24 beds",
        ])
        self.assertTrue(r.detail.startswith("28 places free"))

    def test_available_tissi_26_june(self):
        fetch = self.june(TISSI, "tissi_2027-06.html")
        r = engine.check(TISSI, dt.date(2027, 6, 26), 2, fetch)
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertTrue(r.detail.startswith("33 places free"))  # 10 + 7 + 16
        self.assertEqual(r.options[:2], ["Room with 4 beds: 10 beds", "Dormitory: 7 beds"])
        self.assertTrue(r.options[2].endswith(": 16 beds"))  # label itself says "16 beds"
        self.assert_june_2027_request(fetch, TISSI_URL)

    def test_tissi_room_without_count(self):
        r = engine.check(TISSI, dt.date(2027, 6, 9), 2, self.june(TISSI, "tissi_2027-06.html"))
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertEqual(r.options[0], "1x Private room with 1 bunk-beds (max 2 pers.)")

    # --- guest threshold: green day with fewer beds than guests ----------------
    def test_green_but_too_few_beds_is_full_for_two(self):
        # Lagazuoi 10 Jun: "Dormitories with bunk beds n. 1 beds available"
        r2 = engine.check(LAGAZUOI, dt.date(2027, 6, 10), 2, self.june())
        self.assertEqual(r2.status, Status.FULL)
        self.assertIn("only 1 place(s) free, need 2", r2.detail)
        r1 = engine.check(LAGAZUOI, dt.date(2027, 6, 10), 1, self.june())
        self.assertEqual(r1.status, Status.AVAILABLE)

    def test_tissi_30_june_one_bed(self):
        r = engine.check(TISSI, dt.date(2027, 6, 30), 2, self.june(TISSI, "tissi_2027-06.html"))
        self.assertEqual(r.status, Status.FULL)

    # --- whole month grey (closed season, indistinguishable from sold out) -----
    def test_all_grey_month(self):
        fetch = FakeFetch(fixture_response("lagazuoi_2026-11.html", LAGAZUOI_URL))
        r = engine.check(LAGAZUOI, dt.date(2026, 11, 20), 2, fetch)
        self.assertEqual(r.status, Status.FULL)
        self.assertIn("none (closed season or sold out)", r.detail)
        self.assertEqual(fetch.calls[0][2]["params"], {"prm": 10, "chm": 1})

    # --- month verification / one-shot correction ------------------------------
    def test_wrong_month_is_corrected_once(self):
        nov = fixture_response("lagazuoi_2026-11.html", LAGAZUOI_URL)
        jun = fixture_response("lagazuoi_2027-06.html", LAGAZUOI_URL)
        fetch = FakeFetch(nov, jun)
        r = engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)
        self.assertEqual(r.status, Status.FULL)
        self.assertEqual(len(fetch.calls), 2)
        # got Nov 2026 for index 18 -> shift by +7 months -> index 25
        self.assertEqual(fetch.calls[1][2]["params"], {"prm": 24, "chm": 1})

    def test_wrong_month_twice_raises(self):
        fetch = FakeFetch(fixture_response("lagazuoi_2026-11.html", LAGAZUOI_URL))
        with self.assertRaises(FetchError):
            engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)
        self.assertEqual(len(fetch.calls), 2)

    # --- errors ------------------------------------------------------------------
    def test_fetch_error_propagates(self):
        fetch = FakeFetch(FetchError("HTTP 503 from " + LAGAZUOI_URL))
        with self.assertRaises(FetchError):
            engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)

    def test_http_error_status_raises(self):
        fetch = FakeFetch(fixture_response("x", LAGAZUOI_URL, status=500, body=b"oops"))
        with self.assertRaises(FetchError):
            engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)

    def test_unparseable_body_raises(self):
        fetch = FakeFetch(fixture_response("x", LAGAZUOI_URL, body=b"<html><body>maintenance</body></html>"))
        with self.assertRaises(FetchError):
            engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)

    def test_unknown_day_state(self):
        # In-test minimal edit of the real fixture: day 23's class renamed.
        body = (FIX / "lagazuoi_2027-06.html").read_bytes().replace(
            b'<td class="chiuso" valign="top">23</td>', b'<td class="riservato" valign="top">23</td>'
        )
        fetch = FakeFetch(fixture_response("x", LAGAZUOI_URL, body=body))
        r = engine.check(LAGAZUOI, dt.date(2027, 6, 23), 2, fetch)
        self.assertEqual(r.status, Status.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
