"""Secrets must never reach logs (stdout/stderr, job summary), error lists, issue
titles/bodies or committed state. Positive control: they do reach the places that
need them (ntfy JSON body, Telegram URL, GitHub Authorization header), proving the
sentinels actually flowed through the code under test."""

import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from hutwatch import beds, fast, http, nuvolau, pagewatch, tracker
from hutwatch.beds_config import BedHut, BedNight
from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.notify import Notifier

TOPIC = "SECRETTOPIC-q8x2"
TG = "987654:SECRETTG-zz"
GH = "ghs_SECRETGH-77"
SENTINELS = [TOPIC, TG, GH]


class Leaks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.summary_file = d / "summary.md"
        self.sent = []          # (url, headers, json_body) of every outgoing request
        self.ntfy_calls = 0
        self.page_ok = True
        env = {"NTFY_TOPIC": TOPIC, "TELEGRAM_BOT_TOKEN": TG, "TELEGRAM_CHAT_ID": "42",
               "GITHUB_TOKEN": GH, "GITHUB_REPOSITORY": "me/repo", "GITHUB_REPOSITORY_OWNER": "me",
               "GITHUB_STEP_SUMMARY": str(self.summary_file), "GITHUB_OUTPUT": str(d / "out")}
        hut = Hut("fanes", "Rifugio Fanes", "fake", "https://example.org/book", phone="+39 1")
        engine = types.SimpleNamespace(booking_open=lambda h, f: (True, "form live"),
                                       check=lambda h, n, g, f: CheckResult(Status.AVAILABLE, "2 beds"))
        for p in [
            mock.patch.dict(os.environ, env),
            mock.patch.object(http, "request", self.fake_request),
            mock.patch.object(pagewatch, "STATE_FILE", d / "pages.json"),
            mock.patch.object(beds, "STATE_FILE", d / "beds.json"),
            mock.patch.object(nuvolau, "STATE_FILE", d / "nuvolau.json"),
            mock.patch.object(nuvolau, "OPENING_FILE", d / "nuvolau_opening.json"),
            mock.patch.object(nuvolau, "ANNOUNCE_PAGES", ["https://example.org/nuv"]),
            mock.patch.object(nuvolau, "_engine", lambda: engine),
            mock.patch.object(nuvolau, "sleep", lambda s: None),
            mock.patch.object(beds, "NIGHTS", [BedNight(dt.date(2027, 6, 22), [BedHut(hut, ["Fanes"])])]),
            mock.patch.object(beds, "check_one", self.fake_check),
            mock.patch.object(tracker, "load_or_warn", lambda *a: None),   # also exercises the tracker alert
        ]:
            p.start()
            self.addCleanup(p.stop)
        self.check_fails = True

    def fake_check(self, bh, night):
        if self.check_fails:
            raise http.FetchError(f"HTTP 500 from https://example.org/api?x={TOPIC}")  # hostile echo
        return CheckResult(Status.AVAILABLE, "2 dorm beds")

    def fake_request(self, method, url, *, params=None, data=None, json_body=None, headers=None, **kw):
        self.sent.append((url, dict(headers or {}), json_body))
        ok = lambda body: http.Response(200, url, {"Content-Type": "application/json"}, json.dumps(body).encode())
        if "api.github.com" in url:
            if method == "GET":
                return ok([])
            return ok({"number": 1, "html_url": "https://github.com/me/repo/issues/1"})
        if "ntfy" in url:
            self.ntfy_calls += 1
            if self.ntfy_calls % 2:  # every other push fails, with the topic echoed back
                raise http.FetchError(f"HTTP 500 from {url} [topic {TOPIC} quota]")
            return ok({"id": "x"})
        if "telegram" in url:
            raise http.FetchError(f"HTTP 401 from {url}")  # URL contains the bot token
        if not self.page_ok:
            raise http.FetchError(f"HTTP 503 from {url}")
        page = "<p>Prenotazioni 2027: dal 15 gennaio ore 9</p><p>Stagione 2027 aperta, prenota!</p>" + "x" * 80
        return http.Response(200, url, {"Content-Type": "text/html"}, page.encode())

    def run_everything(self):
        out, err = io.StringIO(), io.StringIO()
        notifiers = []
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            for i in range(4):
                n = Notifier()
                notifiers.append(n)
                if i == 0:
                    fast.send_tests(n)
                self.page_ok = i != 1 and i != 2 and i != 3 or i == 3
                if i in (1, 2):
                    self.page_ok = False
                if i == 3:
                    self.check_fails = False
                pagewatch.run(n, test_alert=(i == 0))
                fast.run(n, schedule="")
        return out.getvalue() + err.getvalue(), notifiers

    def test_no_leaks(self):
        logs, notifiers = self.run_everything()
        errors = "\n".join(e for n in notifiers for e in n.errors)
        gh_bodies = "\n".join(json.dumps(b) for u, h, b in self.sent if "api.github.com" in u)
        state_text = "\n".join(p.read_text() for p in Path(self.tmp.name).glob("*.json"))
        summary = self.summary_file.read_text() if self.summary_file.exists() else ""

        # The scenario really produced output on every channel (else the test proves nothing).
        self.assertTrue(errors and gh_bodies and state_text and summary and logs)
        self.assertIn("ntfy failed", errors)
        self.assertIn("telegram failed", errors)

        for secret in SENTINELS:
            for where, text in [("logs", logs), ("errors", errors), ("issue API bodies", gh_bodies),
                                ("state", state_text), ("job summary", summary)]:
                self.assertNotIn(secret, text, f"{secret!r} leaked into {where}")

        # Positive controls: secrets went where they are needed, and only there.
        self.assertTrue(any(b and b.get("topic") == TOPIC for u, h, b in self.sent if "ntfy" in u))
        self.assertTrue(all(TOPIC not in u for u, h, b in self.sent))          # never in a URL
        self.assertTrue(any(TG in u for u, h, b in self.sent if "telegram" in u))
        self.assertTrue(any(h.get("Authorization") == f"Bearer {GH}" for u, h, b in self.sent
                            if "api.github.com" in u))


if __name__ == "__main__":
    unittest.main()


class IssuesOff(unittest.TestCase):
    def test_body_not_logged_when_issues_off(self):
        env = {"GITHUB_TOKEN": "t" * 10, "GITHUB_REPOSITORY": "me/repo", "HUTWATCH_ISSUES": "off"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(http, "request", side_effect=AssertionError("no API call")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                n = Notifier()
                self.assertIsNone(n.issue("BEDS: X 23 Jun 2027", "SECRET BODY with phone and details"))
        self.assertIn("BEDS: X 23 Jun 2027", out.getvalue())
        self.assertNotIn("SECRET BODY", out.getvalue())
