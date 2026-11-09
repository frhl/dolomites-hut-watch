"""Nuvolau runner: ANNOUNCEMENT / OPENING / BEDS logic with a fake engine and fake pages.
(The real engine's request/parse is tested in test_engine_nuvolau.py.)"""

import datetime as dt
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from hutwatch import detect, fast, http, nuvolau, tracker
from hutwatch.engines.base import CheckResult, Status

T0 = dt.datetime(2027, 1, 10, 8, 0, tzinfo=dt.timezone.utc)
PAGE = "https://example.org/nuvolau"


class Recorder:
    def __init__(self):
        self.issues, self.pushes, self.errors = [], [], []
        self.repo, self.ntfy_topic, self.tg_token, self.tg_chat = "me/repo", "t", "", ""

    def issue(self, title, body, comment_only=False):
        self.issues.append(title)

    def issue_exists(self, title):
        return False

    def ntfy(self, title, message, priority=4, click=None, phone=None, tags=None, **kw):
        self.pushes.append((title, priority, click, message))
        self.delays = getattr(self, "delays", []) + [kw.get("delay")]
        return True

    def telegram(self, text):
        pass


class Announcement(unittest.TestCase):
    def test_positive_with_date_and_time(self):
        s = ["Le prenotazioni per la stagione 2027 apriranno il 15 gennaio 2027 alle ore 9:00."]
        self.assertEqual(detect.announcement_matches(s), s)
        self.assertEqual(detect.when_mentions(s[0]), ["15 gennaio 2027", "alle ore 9:00"])

    def test_positive_english(self):
        s = ["Booking for summer 2027 opens on January 12th at 10 am."]
        self.assertEqual(detect.announcement_matches(s), s)

    def test_split_across_sentences(self):
        s = ["Prenotazioni 2027 a breve.", "Data: 10 gennaio ore 9."]
        self.assertEqual(detect.announcement_matches(s), ["Prenotazioni 2027 a breve. Data: 10 gennaio ore 9."])

    def test_negative_without_date(self):
        self.assertEqual(detect.announcement_matches(["Prenotazioni 2027 non ancora aperte."]), [])

    def test_negative_with_date_still_fires(self):
        s = ["Prenotazioni 2027 non ancora aperte: apertura il 10 gennaio ore 8.30"]
        self.assertEqual(detect.announcement_matches(s), s)

    def test_null_2026_page(self):
        s = ["Rifugio aperto dal 20 giugno 2026.", "Prenota ora!", "Contatti"]
        self.assertEqual(detect.announcement_matches(s), [])


class Runner(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = T0
        self.open = False
        self.beds = {dt.date(2027, 6, 24): CheckResult(Status.CLOSED, "season not bookable yet"),
                     dt.date(2027, 6, 23): CheckResult(Status.CLOSED, "season not bookable yet")}
        self.engine_error = None
        self.page = "<p>Stagione 2026 conclusa. Grazie!</p><p>Contatti e informazioni</p>" + "x" * 60
        self.rows = []
        self.sleeps = []
        engine = types.SimpleNamespace(booking_open=self.fake_open, check=self.fake_check)
        for p in [
            mock.patch.object(nuvolau, "STATE_FILE", Path(tmp.name) / "nuvolau.json"),
            mock.patch.object(nuvolau, "OPENING_FILE", Path(tmp.name) / "nuvolau_opening.json"),
            mock.patch.object(nuvolau, "ANNOUNCE_PAGES", [PAGE]),
            mock.patch.object(nuvolau, "_engine", lambda: engine),
            mock.patch.object(nuvolau, "sleep", self.sleeps.append),
            mock.patch.object(nuvolau.state, "now", lambda: self.now),
            mock.patch.object(nuvolau.state, "today_rome", lambda: self.now.date()),
            mock.patch.object(nuvolau.http, "request", self.fake_request),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def fake_request(self, method, url, **kw):
        if self.engine_error:
            raise self.engine_error
        return http.Response(200, url, {"Content-Type": "text/html; charset=utf-8"}, self.page.encode())

    def fake_open(self, hut, fetch):
        if self.engine_error:
            raise self.engine_error
        return self.open, ("2027 dates bookable" if self.open else "no 2027 dates bookable")

    def fake_check(self, hut, night, guests, fetch):
        assert guests == 2
        if self.engine_error:
            raise self.engine_error
        return self.beds[night]

    def step(self, minutes=5):
        self.now += dt.timedelta(minutes=minutes)
        r = Recorder()
        active = nuvolau.run(r, rows=self.rows)
        return active, r

    def titles(self, r):
        return [p[0] for p in r.pushes]

    def test_not_open_is_quiet(self):
        self.assertEqual(self.step()[1].pushes, [])
        self.assertEqual(self.step()[1].pushes, [])

    def test_announcement_with_date_is_urgent(self):
        self.step()  # baseline page: nothing announced
        self.page = ("<p>Prenotazioni stagione 2027: apertura il 12 gennaio 2027 alle ore 9:00</p>"
                     "<p>Contatti</p>" + "x" * 60)
        r = self.step()[1]
        ann = [p for p in r.pushes if p[0].startswith("ANNOUNCEMENT")]
        self.assertEqual(len(ann), 1)
        self.assertEqual(ann[0][1], 5)
        self.assertIn("12 gennaio 2027", ann[0][3])
        self.assertIn("ANNOUNCEMENT: Nuvolau 2027 booking opening", r.issues)
        self.assertEqual([p for p in self.step()[1].pushes if p[0].startswith("ANNOUNCEMENT")], [])

    def test_first_run_baseline_is_quiet_even_with_dates(self):
        # Like the real homepage: an old Instagram post about last year's staged opening.
        self.page = ("<p>Prenotazioni 2026: dal 1 febbraio alle ore 9:00 20-30 giugno</p>"
                     "<p>Contatti</p>" + "x" * 60)
        r = self.step()[1]
        ann = [p for p in r.pushes if p[0].startswith("ANNOUNCEMENT")]
        self.assertEqual([p[1] for p in ann], [3])

    def test_imminent_pushes_once(self):
        orig = self.fake_open
        self.fake_open = None
        with mock.patch.object(nuvolau, "_engine", lambda: types.SimpleNamespace(
                booking_open=lambda h, f: (False, "bookings still disabled but calendar shows free beds: "
                                                  "opening looks imminent"),
                check=self.fake_check)):
            t1 = [p for p in self.step()[1].pushes if "imminent" in p[0]]
            t2 = [p for p in self.step()[1].pushes if "imminent" in p[0]]
        self.assertEqual((len(t1), len(t2)), (1, 0))
        self.fake_open = orig

    def test_opening_pushes_three_times_once(self):
        self.step()
        self.open = True
        self.beds[dt.date(2027, 6, 24)] = CheckResult(Status.FULL, "full")
        r = self.step()[1]
        self.assertEqual(self.titles(r).count(nuvolau.OPENING_TITLE), 3)
        self.assertTrue(all(p[1] == 5 for p in r.pushes if p[0] == nuvolau.OPENING_TITLE))
        opening_delays = [d for p, d in zip(r.pushes, r.delays) if p[0] == nuvolau.OPENING_TITLE]
        self.assertEqual(opening_delays, [None, "60s", "120s"])  # ntfy-scheduled, no sleeping
        self.assertEqual(self.sleeps, [])
        self.assertEqual(self.titles(self.step()[1]).count(nuvolau.OPENING_TITLE), 0)  # once only

    def test_beds_realert_and_gone(self):
        self.open = True
        self.beds[dt.date(2027, 6, 24)] = CheckResult(Status.AVAILABLE, "2 places in dorm")
        r = self.step()[1]
        self.assertIn("BEDS: Rifugio Nuvolau 24 Jun 2027", self.titles(r))
        self.assertNotIn("BEDS: Rifugio Nuvolau 23 Jun 2027", self.titles(r))
        self.assertNotIn("BEDS: Rifugio Nuvolau 24 Jun 2027", self.titles(self.step(60)[1]))
        self.assertIn("BEDS: Rifugio Nuvolau 24 Jun 2027", self.titles(self.step(60)[1]))  # 2 h
        self.beds[dt.date(2027, 6, 24)] = CheckResult(Status.FULL, "full")
        self.assertIn("GONE: Rifugio Nuvolau 24 Jun 2027", self.titles(self.step()[1]))
        self.assertEqual(self.step()[1].pushes, [])

    def test_fetch_errors_alert_after_three(self):
        self.engine_error = http.FetchError("HTTP 503")
        self.assertEqual(self.step()[1].issues, [])
        self.assertEqual(self.step()[1].issues, [])
        issues = self.step()[1].issues
        self.assertIn("FAILING: Nuvolau opening check", issues)
        self.assertIn("FAILING: Nuvolau announcement watch", issues)
        self.assertIn("FAILING: Rifugio Nuvolau checker", issues)
        self.assertEqual(self.step()[1].issues, [])

    def test_booked_night_24_still_watches_23(self):
        self.rows = [tracker.Row(dt.date(2027, 6, 24), "Rifugio Averau", "Booked", None, None)]
        self.open = True
        self.beds[dt.date(2027, 6, 23)] = CheckResult(Status.AVAILABLE, "1 room")
        self.beds[dt.date(2027, 6, 24)] = CheckResult(Status.AVAILABLE, "1 room")
        t = self.titles(self.step()[1])
        self.assertIn("BEDS: Rifugio Nuvolau 23 Jun 2027", t)
        self.assertNotIn("BEDS: Rifugio Nuvolau 24 Jun 2027", t)

    def test_both_nights_booked_stops(self):
        self.rows = [tracker.Row(dt.date(2027, 6, 24), "Rifugio Nuvolau", "Booked", None, None),
                     tracker.Row(dt.date(2027, 6, 23), "Camping Sass Dlacia chalet", "Booked", None, None)]
        self.engine_error = AssertionError("must not be called")
        active, r = self.step()
        self.assertFalse(active)
        self.assertEqual((r.pushes, r.issues), ([], []))


class FastTicks(unittest.TestCase):
    def test_nuvolau_scope_skips_other_huts(self):
        with mock.patch.object(fast.beds, "run") as b, mock.patch.object(fast.nuvolau, "run") as n, \
                mock.patch.object(fast.tracker, "load_or_warn", lambda: []):
            fast.run(Recorder(), schedule="", scope="nuvolau")
            b.assert_not_called()
            n.assert_called_once()
            fast.run(Recorder(), schedule="", scope="all")
            b.assert_called_once()

    def test_test_alert_sends_one_push_per_type(self):
        r = Recorder()
        fast.send_tests(r)
        self.assertEqual(len(r.pushes), 3)
        self.assertEqual([p[1] for p in r.pushes], [5, 5, 4])
        self.assertTrue(any("ANNOUNCEMENT" in p[0] for p in r.pushes))
        self.assertTrue(any(nuvolau.OPENING_TITLE in p[0] for p in r.pushes))
        self.assertTrue(any("BEDS" in p[0] for p in r.pushes))


if __name__ == "__main__":
    unittest.main()


class WhenParsing(unittest.TestCase):
    def test_month_year_is_not_a_day(self):
        self.assertEqual(detect.when_mentions("Prenotazioni 2027: a partire da gennaio 2027 sul sito web"), [])
        self.assertEqual(detect.when_mentions("possible starting January 2027 on our website"), [])

    def test_real_dates(self):
        self.assertEqual(detect.when_mentions("dal 1 febbraio ore 9"), ["1 febbraio", "ore 9"])


class Dense(unittest.TestCase):
    """1-minute probe loop around 1 Feb."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = 0.0
        self.now = nuvolau.DENSE_START + dt.timedelta(hours=10)
        self.forms = []          # sequence of form states returned by successive probes
        self.calls = 0
        engine = types.SimpleNamespace(_params=lambda hut: {}, fetch_form=self.fake_form,
                                       booking_open=lambda hut, fetch: (True, "form live"))
        for p in [
            mock.patch.object(nuvolau, "OPENING_FILE", Path(tmp.name) / "nuvolau_opening.json"),
            mock.patch.object(nuvolau, "DENSE_FILE", Path(tmp.name) / "nuvolau_dense.json"),
            mock.patch.object(nuvolau, "_engine", lambda: engine),
            mock.patch.object(nuvolau, "sleep", self.fake_sleep),
            mock.patch.object(nuvolau, "monotonic", lambda: self.clock),
            mock.patch.object(nuvolau.state, "now", lambda: self.now),
            mock.patch.object(nuvolau.state, "today_rome", lambda: self.now.date()),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def fake_sleep(self, s):
        self.clock += s

    def fake_form(self, fetch, p):
        self.calls += 1
        item = self.forms.pop(0) if self.forms else False
        if isinstance(item, Exception):
            raise item
        return types.SimpleNamespace(enabled=item, message="Rooms closed")

    def test_outside_window_does_nothing(self):
        self.now = nuvolau.DENSE_START - dt.timedelta(minutes=1)
        self.assertEqual(nuvolau.dense(Recorder(), rows=[]), 0)
        self.assertEqual(self.calls, 0)

    def test_probes_every_minute_fires_once_and_keeps_probing(self):
        self.forms = [False, http.FetchError("HTTP 503"), False, True] + [True] * 200
        r = Recorder()
        nuvolau.dense(r, rows=[])
        # Same number of probes as a block without an opening: the job looks the same.
        self.assertEqual(self.calls, int(nuvolau.DENSE_BLOCK.total_seconds() // nuvolau.DENSE_INTERVAL_S))
        self.assertEqual([p[0] for p in r.pushes], [nuvolau.OPENING_TITLE] * 3)
        self.assertIn(nuvolau.OPENING_ISSUE, r.issues)
        # Lock written: a later job (or the 5-min tick) does not fire again.
        r2 = Recorder()
        self.forms = [True]
        nuvolau.dense(r2, rows=[])
        self.assertEqual(r2.pushes, [])

    def test_block_length_limits_probes(self):
        nuvolau.dense(Recorder(), rows=[])
        self.assertEqual(self.calls, int(nuvolau.DENSE_BLOCK.total_seconds() // nuvolau.DENSE_INTERVAL_S))

    def test_manual_minutes_ignores_window(self):
        self.now = dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc)
        nuvolau.dense(Recorder(), minutes=3, rows=[])
        self.assertEqual(self.calls, 3)

    def test_tick_respects_dense_lock(self):
        nuvolau.state.save(nuvolau.OPENING_FILE, {"alerted": True, "alerted_at": "x", "by": "dense"})
        summary = []
        self.assertTrue(nuvolau.check_opening({}, Recorder(), summary))
        self.assertIn("already alerted", summary[0])
