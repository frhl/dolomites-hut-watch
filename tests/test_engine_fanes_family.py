"""Offline tests for hutwatch.engines.fanes_family (Booking Südtirol widget API).

Fixtures are raw API responses captured 2026-11-08; see tests/fixtures/fanes_family/README.md.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
import urllib.parse
from pathlib import Path

from hutwatch.engines import fanes_family
from hutwatch.engines.base import Hut, Status
from hutwatch.http import FetchError, Response

FIX = Path(__file__).parent / "fixtures" / "fanes_family"
API = "https://api.widgets.bookingsuedtirol.com/v6"

FANES = Hut(id="fanes", name="Rifugio Fanes", engine="fanes_family",
            booking_url="https://www.rifugiofanes.com/en/booking",
            params={"property_id": 13308, "source_id": 98, "max_adults": 5, "max_children": 4})
PEDERUE = Hut(id="pederue", name="Berggasthaus Pederü", engine="fanes_family",
              booking_url="https://www.pederue.it/en#Y7D0a11V",
              params={"property_id": 10716, "source_id": 98, "max_adults": 4, "max_children": 3})
LAVARELLA = Hut(id="lavarella", name="Rifugio Lavarella", engine="fanes_family",
                booking_url="https://www.lavarella.it/en/book-online",
                params={"property_id": 13004, "source_id": 98, "max_adults": 5, "max_children": 3})
FODARA = Hut(id="fodara_vedla", name="Rifugio Fodara Vedla", engine="fanes_family",
             booking_url="https://www.fodara.it/en#q9ShPDKO",
             params={"property_id": 12869, "source_id": 98, "max_adults": 8, "max_children": 3})

ROOM2 = [[18, 18]]       # one room for two adults
SPLIT = [[18], [18]]     # two 1-person units (dorm beds / singles)
TARGET = dt.date(2027, 6, 22)


class FakeFetch:
    """Routes (endpoint, guests layout) -> fixture file; records every call."""

    def __init__(self, routes: dict[tuple, str | Exception]):
        self.routes = routes
        self.calls: list[dict] = []

    def __call__(self, method, url, *, params=None, headers=None, **kw):
        self.calls.append({"method": method, "url": url, "params": dict(params or {}),
                           "headers": dict(headers or {}), **kw})
        endpoint = url.rsplit("/", 1)[1]
        guests = params.get("guests") if params else None
        key = (endpoint, json.loads(guests) if guests else None)
        key = (key[0], json.dumps(key[1]))
        target = self.routes.get(key, self.routes.get((endpoint, "*")))
        if target is None:
            raise AssertionError(f"unexpected request {method} {url} {params}")
        if isinstance(target, Exception):
            raise target
        full = url + "?" + urllib.parse.urlencode(params or {})
        return Response(status=200, url=full, headers={"Content-Type": "application/json"},
                        body=(FIX / target).read_bytes() if not isinstance(target, bytes) else target)

    def by_endpoint(self, endpoint):
        return [c for c in self.calls if c["url"].endswith("/" + endpoint)]


def route(endpoint, guests, target):
    return ((endpoint, json.dumps(guests) if guests != "*" else "*"), target)


def avail_routes(hut_prefix, room2=None, split=None):
    return dict([
        route("availabilities", ROOM2, room2 or f"{hut_prefix}_avail_2027-06_room2.json"),
        route("availabilities", SPLIT, split or f"{hut_prefix}_avail_2027-06_split1x2.json"),
    ])


class AvailabilityRequestShape(unittest.TestCase):
    def assert_availability_requests(self, fake, property_id, frm, to):
        calls = fake.by_endpoint("availabilities")
        self.assertEqual(len(calls), 2)
        layouts = []
        for c in calls:
            self.assertEqual(c["method"], "GET")
            self.assertEqual(c["url"], f"{API}/properties/{property_id}/availabilities")
            self.assertEqual(c["headers"].get("Accept"), "application/json")
            p = c["params"]
            self.assertEqual(p["from"], frm)
            self.assertEqual(p["to"], to)
            self.assertEqual(p["sourceId"], 98)
            rooms = json.loads(p["guests"])
            # exactly 2 guests, all adults
            self.assertEqual(sum(len(r) for r in rooms), 2)
            self.assertTrue(all(age == 18 for r in rooms for age in r))
            layouts.append(rooms)
        self.assertCountEqual(layouts, [ROOM2, SPLIT])
        for c in calls:  # no write methods, no bodies
            self.assertNotIn("data", c)
            self.assertNotIn("json_body", c)


class TestFull(AvailabilityRequestShape):
    def test_fanes_target_night_full(self):
        fake = FakeFetch(avail_routes("fanes"))
        res = fanes_family.check(FANES, TARGET, 2, fake)
        self.assertEqual(res.status, Status.FULL)
        self.assertIn("no bookable stay covering 22 Jun 2027 for 2", res.detail)
        self.assert_availability_requests(fake, 13308, "2027-06-01", "2027-06-30")
        self.assertEqual(fake.by_endpoint("offers"), [])
        self.assertEqual(len(res.options), 2)

    def test_pederue_fodara_lavarella_target_night_full(self):
        for hut, prefix in ((PEDERUE, "pederue"), (FODARA, "fodara"), (LAVARELLA, "lavarella")):
            with self.subTest(hut=hut.id):
                fake = FakeFetch(avail_routes(prefix))
                res = fanes_family.check(hut, TARGET, 2, fake)
                self.assertEqual(res.status, Status.FULL)
                self.assert_availability_requests(fake, hut.params["property_id"],
                                                  "2027-06-01", "2027-06-30")

    def test_lavarella_june_is_on_sale_but_late_june_empty(self):
        fake = FakeFetch(avail_routes("lavarella"))
        res = fanes_family.check(LAVARELLA, TARGET, 2, fake)
        self.assertEqual(res.status, Status.FULL)  # arrivals 5-16 Jun exist, so not CLOSED
        self.assertIn("nothing bookable online from 22 Jun 2027 to 30 Jun 2027 either", res.detail)

    def test_fanes_full_with_later_availability_has_no_trailing_note(self):
        res = fanes_family.check(FANES, TARGET, 2, FakeFetch(avail_routes("fanes")))
        self.assertNotIn("either", res.detail)  # 23 Jun is bookable later in the window


class TestClosed(AvailabilityRequestShape):
    def test_empty_window_is_closed_not_on_sale(self):
        fake = FakeFetch(dict([route("availabilities", "*", b"[]")]))
        res = fanes_family.check(LAVARELLA, dt.date(2027, 7, 3), 2, fake)
        self.assertEqual(res.status, Status.CLOSED)
        self.assertIn("not open for online booking yet", res.detail)
        # early in the month the window reaches back `lookback_days` (14) into June
        self.assert_availability_requests(fake, 13004, "2027-06-19", "2027-07-31")


class TestAvailable(AvailabilityRequestShape):
    def test_fodara_one_night_available(self):
        routes = avail_routes("fodara")
        routes.update([route("offers", ROOM2, "fodara_offers_2027-06-23_1night_room2.json"),
                       route("rooms", "*", "fodara_rooms_en.json")])
        fake = FakeFetch(routes)
        night = dt.date(2027, 6, 23)
        res = fanes_family.check(FODARA, night, 2, fake)
        self.assertEqual(res.status, Status.AVAILABLE)
        self.assertIn("1 room for 2, 2027-06-23 -> 2027-06-24 (1 night)", res.detail)
        self.assertFalse(res.split)
        self.assertIn("Lager up to 6 person x1 free from EUR 238", res.detail)
        self.assertNotIn("refused", res.detail)
        self.assert_availability_requests(fake, 12869, "2027-06-01", "2027-06-30")
        (offers,) = fake.by_endpoint("offers")
        p = offers["params"]
        self.assertEqual((p["from"], p["to"]), ("2027-06-23", "2027-06-24"))
        self.assertEqual(json.loads(p["guests"]), ROOM2)
        self.assertEqual((p["sourceId"], p["lang"]), (98, "en"))

    def test_details_failure_does_not_mask_availability(self):
        routes = avail_routes("fodara")
        routes.update([route("offers", ROOM2, FetchError("HTTP 500"))])
        res = fanes_family.check(FODARA, dt.date(2027, 6, 23), 2, FakeFetch(routes))
        self.assertEqual(res.status, Status.AVAILABLE)
        self.assertTrue(res.detail.endswith("(1 night)"))


class TestOneNightMinimumRefused(AvailabilityRequestShape):
    def test_fanes_1_night_refused_but_2_nights_bookable(self):
        """Real response: arrival 2027-06-23 -> 06-24 is minimum_stay_not_fulfilled,
        -> 06-25 is departure_possible. Per-night answer: the night is free."""
        routes = avail_routes("fanes")
        routes.update([route("offers", ROOM2, "fanes_offers_2027-06-23_2nights_room2.json"),
                       route("rooms", "*", "fanes_rooms_en.json")])
        fake = FakeFetch(routes)
        res = fanes_family.check(FANES, dt.date(2027, 6, 23), 2, fake)
        self.assertEqual(res.status, Status.AVAILABLE)
        self.assertIn("2027-06-23 -> 2027-06-25 (2 nights)", res.detail)
        self.assertIn("1-night stay refused: minimum stay", res.detail)
        self.assertIn("Sas dles Diesc, private bathroom x1 free from EUR 692", res.detail)
        self.assert_availability_requests(fake, 13308, "2027-06-01", "2027-06-30")
        (offers,) = fake.by_endpoint("offers")
        self.assertEqual((offers["params"]["from"], offers["params"]["to"]),
                         ("2027-06-23", "2027-06-25"))

    def test_only_refused_stays_cover_night_gives_min_stay(self):
        """EDITED fixture: the 06-23 -> 06-25 stay removed, only the refused 1-night left."""
        fake = FakeFetch(avail_routes(
            "fanes", room2="fanes_avail_2027-06_room2_EDITED_minstay_only.json"))
        res = fanes_family.check(FANES, dt.date(2027, 6, 23), 2, fake)
        self.assertEqual(res.status, Status.MIN_STAY)
        self.assertIn("minimum stay", res.detail)
        self.assertEqual(fake.by_endpoint("offers"), [])

    def test_offers_endpoint_cannot_tell_refused_from_full(self):
        """Why the engine uses /availabilities: the offers body for a refused 1-night stay
        (night free) equals the body for the full target night."""
        refused = json.loads((FIX / "fanes_offers_2027-06-23_1night_room2_minstay_refused.json")
                             .read_text())
        full = json.loads((FIX / "fanes_offers_2027-06-22_1night_room2.json").read_text())
        self.assertEqual(refused, full)
        self.assertEqual(refused["rates"], [])


class TestErrors(unittest.TestCase):
    def test_fetch_error_propagates(self):
        def boom(*a, **kw):
            raise FetchError("HTTP 503 from api.widgets.bookingsuedtirol.com")
        with self.assertRaises(FetchError):
            fanes_family.check(FANES, TARGET, 2, boom)

    def test_unparseable_bodies_raise_fetch_error(self):
        for body in (b"<html>maintenance</html>", b'{"error": "x"}',
                     b'[{"date": "2027-06-22"}]', b'[{"date": "bad", "departures": []}]'):
            with self.subTest(body=body):
                fake = FakeFetch(dict([route("availabilities", "*", body)]))
                with self.assertRaises(FetchError):
                    fanes_family.check(FANES, TARGET, 2, fake)


if __name__ == "__main__":
    unittest.main()
