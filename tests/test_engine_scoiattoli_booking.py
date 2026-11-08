"""Offline tests for hutwatch.engines.scoiattoli_booking (fixtures recorded 2026-11-08).

See tests/fixtures/scoiattoli_booking/README.md for the exact request behind each file.

Min-stay: this engine has none. A 1-night query on New Year's Eve (the night most
likely to carry a minimum stay) came back as a plain "no places" with other 1-night
dates suggested, so MIN_STAY is never returned and there is no min-stay fixture.
"""

from __future__ import annotations

import datetime as dt
import unittest
from pathlib import Path

from hutwatch.engines import scoiattoli_booking as engine
from hutwatch.engines.base import Hut, Status
from hutwatch.http import FetchError, Response

FIX = Path(__file__).parent / "fixtures" / "scoiattoli_booking"
URL = "https://www.rifugioscoiattoli.it/booking/"
HUT = Hut(
    id="scoiattoli", name="Rifugio Scoiattoli", engine="scoiattoli_booking",
    booking_url=URL, params={"url": URL},
)
TARGET = dt.date(2027, 6, 23)


def response(name: str | None = None, *, body: bytes | None = None, status: int = 200) -> Response:
    return Response(
        status=status, url=URL,
        headers={"Content-Type": "text/html; charset=UTF-8"},
        body=(FIX / name).read_bytes() if body is None else body,
    )


def edited(name: str, *replacements: tuple[str, str]) -> Response:
    text = (FIX / name).read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, f"{old!r} not in {name}"
        text = text.replace(old, new, 1)
    return response(body=text.encode("utf-8"))


class FakeFetch:
    """Returns one queued item per call; exceptions are raised."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kw):
        self.calls.append((method, url, kw))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class ScoiattoliBookingTest(unittest.TestCase):
    def assert_request(self, fetch: FakeFetch, night: dt.date, guests: int = 2):
        self.assertEqual(len(fetch.calls), 1)
        method, url, kw = fetch.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, URL)
        self.assertEqual(kw.get("params"), {
            "action": "invia",
            "arrivo_insert": night.isoformat(),                               # check-in
            "partenza_insert": (night + dt.timedelta(days=1)).isoformat(),    # check-out
            "nadulti": guests,
            "nbambini_3_12": 0,
            "nbambini_0_2": 0,
        })
        self.assertNotIn("data", kw)
        self.assertNotIn("json_body", kw)

    # --- target night: 23 Jun 2027 is sold out -> FULL -------------------------
    def test_full_target_night(self):
        fetch = FakeFetch(response("target_2027-06-23_full.html"))
        r = engine.check(HUT, TARGET, 2, fetch)
        self.assert_request(fetch, TARGET)
        self.assertEqual(fetch.calls[0][2]["params"]["arrivo_insert"], "2027-06-23")
        self.assertEqual(fetch.calls[0][2]["params"]["partenza_insert"], "2027-06-24")
        self.assertEqual(fetch.calls[0][2]["params"]["nadulti"], 2)
        self.assertEqual(r.status, Status.FULL)
        self.assertIn("no places for 2", r.detail)
        self.assertIn("no nearby dates offered", r.detail)
        self.assertIn("waiting list", r.detail)

    def test_full_with_alternative_dates(self):
        night = dt.date(2026, 12, 31)
        fetch = FakeFetch(response("full_alternatives_2026-12-31.html"))
        r = engine.check(HUT, night, 2, fetch)
        self.assert_request(fetch, night)
        self.assertEqual(r.status, Status.FULL)
        self.assertIn("28/12, 29/12, 30/12, 02/01, 03/01", r.detail)

    # --- available ------------------------------------------------------------
    def test_available_one_dorm(self):
        night = dt.date(2027, 1, 12)
        fetch = FakeFetch(response("available_2027-01-12.html"))
        r = engine.check(HUT, night, 2, fetch)
        self.assert_request(fetch, night)
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertTrue(r.detail.startswith("8 places free"), r.detail)
        self.assertEqual(r.options, ["Camerata 9: 8 beds free (110.00 € a notte a letto)"])

    def test_available_two_dorms(self):
        night = dt.date(2027, 9, 28)
        fetch = FakeFetch(response("available_2027-09-28.html"))
        r = engine.check(HUT, night, 2, fetch)
        self.assert_request(fetch, night)
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertTrue(r.detail.startswith("4 places free"), r.detail)
        self.assertEqual(r.options, [
            "Camerata 9: 3 beds free (110.00 € a notte a letto)",
            "Camerata 1: 1 bed free (110.00 € a notte a letto)",
        ])

    def test_fewer_places_than_guests_is_full(self):
        # In-memory edit: same 4 free beds, but the party is 5 (echo edited to match).
        night = dt.date(2027, 9, 28)
        fetch = FakeFetch(edited("available_2027-09-28.html",
                                 ("<b>N. Adulti:</b> 2", "<b>N. Adulti:</b> 5")))
        r = engine.check(HUT, night, 5, fetch)
        self.assert_request(fetch, night, guests=5)
        self.assertEqual(r.status, Status.FULL)
        self.assertIn("only 4 place(s) free, need 5", r.detail)

    def test_private_room_checkbox(self):
        # Synthetic, in-memory: no real response offered a private room. The markup
        # follows the page's own JS ($('.chk_id_camera:checked').data('letti') inside
        # a <label>); the dorm is emptied so only the room can make it AVAILABLE.
        night = dt.date(2027, 1, 12)
        room = ("<label class='labelCamera'><p><b>Camera 3</b></p>"
                "<input type='checkbox' class='chk_id_camera' name='id_camera[3]' "
                "value='1' data-letti='2' /><p class='descr'>Camera doppia"
                "<br/><b>130.00 &euro; a notte a persona</b></p></label>")
        fetch = FakeFetch(edited(
            "available_2027-01-12.html",
            ("<div class='labelContainer'>", "<div class='labelContainer'>" + room),
            ("<option value='1' >1 letti</option>", ""),
            ("<option value='2' >2 letti</option>", ""),
            ("<option value='3' >3 letti</option>", ""),
            ("<option value='4' >4 letti</option>", ""),
            ("<option value='5' >5 letti</option>", ""),
            ("<option value='6' >6 letti</option>", ""),
            ("<option value='7' >7 letti</option>", ""),
            ("<option value='8' >8 letti</option>", ""),
        ))
        r = engine.check(HUT, night, 2, fetch)
        self.assertEqual(r.status, Status.AVAILABLE)
        self.assertEqual(r.options, ["Camera 3: room for 2 (130.00 € a notte a persona)"])

    # --- closed ---------------------------------------------------------------
    def test_closed_outside_season(self):
        night = dt.date(2027, 5, 5)
        fetch = FakeFetch(response("closed_2027-05-05.html"))
        r = engine.check(HUT, night, 2, fetch)
        self.assert_request(fetch, night)
        self.assertEqual(r.status, Status.CLOSED)

    # --- unknown / errors -----------------------------------------------------
    def test_unrecognised_message_is_unknown(self):
        fetch = FakeFetch(edited(
            "target_2027-06-23_full.html",
            ("Non ci sono posti disponibili per le date selezionate",
             "Soggiorno minimo 2 notti"),
        ))
        r = engine.check(HUT, TARGET, 2, fetch)
        self.assertEqual(r.status, Status.UNKNOWN)
        self.assertIn("Soggiorno minimo 2 notti", r.detail)

    def test_fetch_error_propagates(self):
        fetch = FakeFetch(FetchError("TimeoutError fetching " + URL))
        with self.assertRaises(FetchError):
            engine.check(HUT, TARGET, 2, fetch)
        self.assert_request(fetch, TARGET)

    def test_http_error_status_raises(self):
        fetch = FakeFetch(response(body=b"<html>Internal Server Error</html>", status=500))
        with self.assertRaises(FetchError):
            engine.check(HUT, TARGET, 2, fetch)

    def test_unparseable_body_raises(self):
        # e.g. the empty search form, or a WAF page: no Arrivo/Partenza/N. Adulti echo.
        fetch = FakeFetch(response(body=b"<html><form id='form_prenotazione'></form></html>"))
        with self.assertRaises(FetchError):
            engine.check(HUT, TARGET, 2, fetch)

    def test_echo_for_other_dates_raises(self):
        # The site answered for 23-24 Jun, but we asked for 22-23 Jun.
        fetch = FakeFetch(response("target_2027-06-23_full.html"))
        with self.assertRaises(FetchError):
            engine.check(HUT, dt.date(2027, 6, 22), 2, fetch)

    def test_echo_for_other_guest_count_raises(self):
        fetch = FakeFetch(response("target_2027-06-23_full.html"))
        with self.assertRaises(FetchError):
            engine.check(HUT, TARGET, 3, fetch)

    def test_booking_url_used_when_no_param(self):
        hut = Hut(id="scoiattoli", name="Rifugio Scoiattoli",
                  engine="scoiattoli_booking", booking_url=URL)
        fetch = FakeFetch(response("target_2027-06-23_full.html"))
        engine.check(hut, TARGET, 2, fetch)
        self.assertEqual(fetch.calls[0][1], URL)


if __name__ == "__main__":
    unittest.main()
