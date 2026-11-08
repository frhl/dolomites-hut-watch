import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hutwatch import beds, http, tracker
from hutwatch.beds_config import BedHut, BedNight
from hutwatch.engines.base import CheckResult, Hut, Status

N22 = dt.date(2027, 6, 22)
T0 = dt.datetime(2027, 1, 10, 12, 0, tzinfo=dt.timezone.utc)


class Recorder:
    def __init__(self):
        self.issues, self.pushes, self.errors = [], [], []
        self.repo, self.ntfy_topic, self.tg_token, self.tg_chat = "me/repo", "t", "", ""

    def issue(self, title, body, comment_only=False):
        self.issues.append((title, comment_only))

    def ntfy(self, title, message, priority=4, click=None, phone=None, tags=None, **kw):
        self.pushes.append((title, priority, click, phone))
        return True

    def telegram(self, text):
        pass


class BedsRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        hut = Hut("fanes", "Rifugio Fanes", "fake", "https://example.org/book", phone="+39 1")
        self.nights = [BedNight(N22, [BedHut(hut, ["Rifugio Fanes"])])]
        self.result: object = CheckResult(Status.FULL, "full")
        self.now = T0
        self.rows = [tracker.Row(N22, "Rifugio Fanes", "Enquiry needed", "+39 0474 453001", None)]
        for p in [
            mock.patch.object(beds, "STATE_FILE", Path(self.tmp.name) / "beds.json"),
            mock.patch.object(beds, "NIGHTS", self.nights),
            mock.patch.object(beds, "check_one", self.fake_check),
            mock.patch.object(beds.state, "now", lambda: self.now),
            mock.patch.object(beds.state, "today_rome", lambda: self.now.date()),
            mock.patch.object(tracker, "load_or_warn", lambda *a: self.rows),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def fake_check(self, bh, night):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def step(self, minutes=15):
        self.now += dt.timedelta(minutes=minutes)
        r = Recorder()
        beds.run(r)
        return (1 if r.errors else 0), r

    def test_full_is_silent(self):
        rc, r = self.step()
        self.assertEqual((rc, r.issues, r.pushes), (0, [], []))

    def test_available_alert_realert_gone(self):
        self.step()
        self.result = CheckResult(Status.AVAILABLE, "2 dorm beds")
        rc, r = self.step()
        self.assertEqual(r.pushes, [("BEDS: Rifugio Fanes 22 Jun 2027", 4, "https://example.org/book",
                                     "+39 0474 453001")])          # phone from tracker
        self.assertEqual(r.issues, [("BEDS: Rifugio Fanes 22 Jun 2027", False)])
        self.assertEqual(self.step(60)[1].pushes, [])                # within 2 h: quiet
        self.assertEqual(len(self.step(60)[1].pushes), 1)            # 2 h since alert: re-alert
        self.result = CheckResult(Status.FULL, "full")
        r = self.step()[1]
        self.assertEqual([p[0] for p in r.pushes], ["GONE: Rifugio Fanes 22 Jun 2027"])
        self.assertEqual(self.step()[1].pushes, [])                  # one gone notice only

    def test_split_is_labelled(self):
        self.step()
        self.result = CheckResult(Status.AVAILABLE, "1 bed in A; 1 bed in B", split=True)
        pushes, issues = [], []
        with mock.patch.object(Recorder, "issue", lambda s, t, b, comment_only=False: issues.append(b)), \
                mock.patch.object(Recorder, "ntfy", lambda s, title, message, **k: pushes.append(message) or True):
            self.step()
        self.assertEqual(len(pushes), 1)
        self.assertTrue(pushes[0].startswith("SPLIT across rooms: 1 bed in A"))
        self.assertIn("beds are in different rooms", issues[0])

    def test_three_failures_alert_once_and_recover(self):
        self.result = http.FetchError("HTTP 500")
        self.assertEqual(self.step()[1].pushes, [])
        self.assertEqual(self.step()[1].pushes, [])
        r = self.step()[1]
        self.assertEqual([i[0] for i in r.issues], ["FAILING: Rifugio Fanes checker"])
        self.assertEqual(len(r.pushes), 1)
        self.assertEqual(self.step()[1].issues, [])
        self.result = CheckResult(Status.FULL, "full")
        r = self.step()[1]
        self.assertEqual(r.issues, [("FAILING: Rifugio Fanes checker", True)])

    def test_unknown_counts_as_failure(self):
        self.result = CheckResult(Status.UNKNOWN, "weird page")
        for _ in range(2):
            self.step()
        self.assertEqual([i[0] for i in self.step()[1].issues], ["FAILING: Rifugio Fanes checker"])

    def test_booked_in_tracker_stops_night(self):
        self.rows = [tracker.Row(N22, "Rifugio Lavarella", "Booked", None, None)]
        self.result = AssertionError("should not be called")
        rc, r = self.step()
        self.assertEqual((rc, r.issues), (0, []))
        self.assertFalse(beds.run(Recorder()))     # no active night -> False (workflow disables)

    def test_date_passed_stops(self):
        self.now = dt.datetime(2027, 6, 23, 8, 0, tzinfo=dt.timezone.utc)
        self.result = AssertionError("should not be called")
        rc, r = self.step()
        self.assertEqual((rc, r.issues), (0, []))

    def test_night_itself_still_checked(self):
        self.now = dt.datetime(2027, 6, 22, 6, 0, tzinfo=dt.timezone.utc)
        self.result = CheckResult(Status.AVAILABLE, "1 room")
        self.assertEqual(len(self.step()[1].pushes), 1)


class TrackerFile(unittest.TestCase):
    def test_reads_tracker_layout(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Nights"
        ws.append(["Alta Via 1: where we sleep"])          # title rows above the header, like the real one
        ws.append(["Night", "Plan / Backup", "Place", "Status", "Phone", "Notes"])
        ws.append([dt.datetime(2027, 6, 22), "Plan", "Rifugio Fanes", "Enquiry needed", "+39 0474 453001", "x"])
        ws.append([dt.datetime(2027, 6, 22), "Backup", "Berggasthaus Pederü", "Not checked", None, None])
        ws.append([dt.datetime(2027, 6, 23), "Backup", "Rifugio Lagazuoi", "Full", None, None])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.xlsx"
            wb.save(path)
            rows = tracker.load(path)
        fanes = tracker.find(rows, N22, ["Rifugio Fanes"])
        self.assertEqual(fanes.phone, "+39 0474 453001")
        self.assertIsNotNone(tracker.find(rows, N22, ["Pederu"]))        # accents ignored
        self.assertIsNotNone(tracker.find(rows, dt.date(2027, 6, 23), ["Lagazuoi"]))

    def test_booked_detection(self):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Nights"
        ws.append(["title"])
        ws.append(["Night", "Plan / Backup", "Place", "Status", "Phone"])
        ws.append([dt.datetime(2027, 6, 23), "Plan", "Camping Sass Dlacia chalet", "Booked", None])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.xlsx"
            wb.save(p)
            rows = tracker.load(p)
        self.assertEqual(tracker.night_booked(rows, dt.date(2027, 6, 23)).place, "Camping Sass Dlacia chalet")
        self.assertIsNone(tracker.night_booked(rows, N22))


if __name__ == "__main__":
    unittest.main()


class BlockedOnCi(unittest.TestCase):
    def test_skipped_on_github_runner_only(self):
        hut = Hut("fanes", "Rifugio Fanes", "fake", "u", params={"blocked_on_ci": True})
        calls = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(beds, "STATE_FILE", Path(d) / "b.json"), \
                mock.patch.object(beds, "NIGHTS", [BedNight(N22, [BedHut(hut, ["Fanes"])])]), \
                mock.patch.object(beds, "check_one", lambda bh, n: calls.append(1) or CheckResult(Status.FULL, "")), \
                mock.patch.object(beds.state, "today_rome", lambda: dt.date(2027, 1, 1)):
            with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
                beds.run(Recorder(), rows=[])
            self.assertEqual(calls, [])
            with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": ""}):
                beds.run(Recorder(), rows=[])
            self.assertEqual(calls, [1])


class NothingPrivateInPublicTree(unittest.TestCase):
    """State and tracker live in the private repo (./private, git-ignored)."""

    def test_defaults_point_into_private(self):
        root = Path(tracker.__file__).resolve().parent.parent
        self.assertEqual(tracker.DEFAULT_PATH.parent, root / "private") if not \
            __import__("os").environ.get("HUTWATCH_TRACKER") else None
        self.assertFalse((root / "AV1-booking-tracker.xlsx").exists())
        self.assertFalse((root / "state").exists())
        self.assertIn("private/", (root / ".gitignore").read_text().split())
