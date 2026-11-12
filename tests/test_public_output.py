"""Public outputs must not depend on availability.

Two worlds share the same baseline run, then differ on the second run:
  QUIET   everything full/closed, pages unchanged, Nuvolau closed
  EVENTS  beds available, Nuvolau booking open + announcement with a date, a page changed
Everything public (run log, job summary, STATUS.md, files outside ./private) must be
byte-identical between the two. Positive control: EVENTS really sent alerts, QUIET none.
"""

import contextlib
import datetime as dt
import io
import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from hutwatch import beds, fast, http, nuvolau, pagewatch, status, tracker
from hutwatch.engines.base import CheckResult, Status
from hutwatch.notify import Notifier

T1 = dt.datetime(2027, 1, 10, 8, 0, tzinfo=dt.timezone.utc)
T2 = T1 + dt.timedelta(minutes=15)
FULL_PAGE = "<p>Apertura/Open : Sabato 6 giugno 2026</p><p>Contatti e informazioni</p>" + "x" * 80
EVENT_PAGE = ("<p>Apertura/Open : Sabato 5 giugno 2027</p><p>Prenotazioni 2027: apertura il 12 gennaio "
              "2027 alle ore 9:00</p>" + "x" * 80)
ALLOWED = re.compile(
    r"^(checked .+: (ok|FAIL \([^)]*\)|skipped on GitHub \(checked from the Mac\)|"
    r"not checked \(night no longer watched\)|not in the dense window, nothing to do)"
    r"|checked Nuvolau booking form \d+ times: \d+ ok, \d+ failed"
    r"|skipped (hut|Nuvolau|page) checks: backup schedule, last run under \d+ min ago)$")


class World:
    def __init__(self, events: bool):
        self.events = events
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pushes = []
        self.second = False

    # --- fakes ---
    def request(self, method, url, *, json_body=None, **kw):
        if "ntfy" in url:
            self.pushes.append(json_body.get("title"))
            return http.Response(200, url, {}, b"{}")
        page = EVENT_PAGE if (self.events and self.second) else FULL_PAGE
        return http.Response(200, url, {"Content-Type": "text/html; charset=utf-8"}, page.encode())

    def check_one(self, bh, night):
        if self.events and self.second:
            return CheckResult(Status.AVAILABLE, "2 dorm beds", split=False)
        return CheckResult(Status.FULL, "full")

    def booking_open(self, hut, fetch):
        return (True, "form live") if (self.events and self.second) else (False, "bookings disabled")

    def nuv_check(self, hut, night, guests, fetch):
        if self.events and self.second:
            return CheckResult(Status.AVAILABLE, "2 beds")
        return CheckResult(Status.CLOSED, "bookings disabled")

    def fetch_form(self, fetch, p):
        return types.SimpleNamespace(enabled=self.events and self.second, message="m")

    # --- one run of every public entry point ---
    def run(self, now):
        engine = types.SimpleNamespace(booking_open=self.booking_open, check=self.nuv_check,
                                       fetch_form=self.fetch_form, _params=lambda h: {})
        summary = self.dir / "summary.md"
        summary.write_text("")
        env = {"HUTWATCH_PUBLIC_LOG": "1", "NTFY_TOPIC": "topic-xyz123", "GITHUB_TOKEN": "",
               "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_ACTIONS": "true", "GITHUB_OUTPUT": ""}
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(http, "request", self.request), \
                mock.patch.object(beds, "check_one", self.check_one), \
                mock.patch.object(nuvolau, "_engine", lambda: engine), \
                mock.patch.object(nuvolau, "sleep", lambda s: None), \
                mock.patch.object(nuvolau, "monotonic", iter(range(0, 10_000, 60)).__next__), \
                mock.patch.object(tracker, "load_or_warn", lambda *a: []), \
                mock.patch.object(beds.state, "now", lambda: now), \
                mock.patch.object(beds.state, "today_rome", lambda: now.date()), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            n = Notifier()
            pagewatch.run(n)
            fast.run(n, schedule="")
            nuvolau.dense(n, minutes=3, rows=[])
            text = status.render(now=now)
        return out.getvalue(), summary.read_text(), text

    def __enter__(self):
        d = self.dir
        self.patches = [
            mock.patch.object(pagewatch, "STATE_FILE", d / "pages.json"),
            mock.patch.object(beds, "STATE_FILE", d / "beds.json"),
            mock.patch.object(nuvolau, "STATE_FILE", d / "nuvolau.json"),
            mock.patch.object(nuvolau, "OPENING_FILE", d / "nuvolau_opening.json"),
            mock.patch.object(nuvolau, "DENSE_FILE", d / "nuvolau_dense.json"),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def both_runs(self):
        self.run(T1)
        self.second = True
        return self.run(T2)


class PublicOutputIsAvailabilityBlind(unittest.TestCase):
    def test_identical_public_output(self):
        with World(events=False) as quiet:
            q_log, q_summary, q_status = quiet.both_runs()
            q_pushes = list(quiet.pushes)
        with World(events=True) as ev:
            e_log, e_summary, e_status = ev.both_runs()
            e_pushes = list(ev.pushes)

        # Positive control: the EVENTS world really produced alerts of every kind.
        self.assertEqual(q_pushes, [])
        # OPEN already covers Pian de Fontana's page: no second push for the same change.
        self.assertNotIn("IMPORTANT: Pian de Fontana page changed", e_pushes)
        self.assertNotIn("IMPORTANT: Nuvolau page changed", e_pushes)  # ANNOUNCEMENT covers it
        for title in ["BEDS: Rifugio Biella 22 Jun 2027", nuvolau.OPENING_TITLE,
                      "ANNOUNCEMENT: Nuvolau 2027 booking", "OPEN: Pian de Fontana 2027 bookings",
                      "IMPORTANT: Sennes page changed"]:
            self.assertIn(title, e_pushes)

        self.assertEqual(q_log, e_log)
        self.assertEqual(q_summary, e_summary)
        self.assertEqual(q_status, e_status)

        # And the log contains only health lines.
        lines = [ln for ln in e_log.splitlines() if ln.strip()]
        self.assertTrue(lines)
        for ln in lines:
            self.assertRegex(ln, ALLOWED)
        for word in ["available", "full", "beds", "BEDS", "OPEN", "ANNOUNCEMENT", "gennaio", "topic-xyz123"]:
            self.assertNotIn(word, e_log + e_summary + e_status)

    def test_status_shows_only_run_times_and_health(self):
        with World(events=True) as ev:
            _, _, text = ev.both_runs()
        self.assertIn("| page-watch (every 4 h) | 2027-01-10 08:15 |", text)
        self.assertIn("| 22 Jun 2027 | Rifugio Biella | cancellation-watch | OK |", text)
        self.assertIn("| 22 Jun 2027 | Rifugio Fanes | Mac (hourly) | not published |", text)


if __name__ == "__main__":
    unittest.main()
