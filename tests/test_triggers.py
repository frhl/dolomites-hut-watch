"""External trigger (cron-job.org -> workflow_dispatch) and the GitHub-cron backup guard."""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hutwatch import beds, fast, nuvolau, pagewatch, state

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2027, 1, 10, 8, 0, tzinfo=dt.timezone.utc)


def load_setup():
    spec = importlib.util.spec_from_file_location("setup_triggers", ROOT / "scripts/setup_triggers.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class BackupGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.bf, self.nf, self.pf = d / "beds.json", d / "nuvolau.json", d / "pages.json"
        self.patches = [mock.patch.object(beds, "STATE_FILE", self.bf),
                        mock.patch.object(nuvolau, "STATE_FILE", self.nf),
                        mock.patch.object(pagewatch, "STATE_FILE", self.pf),
                        mock.patch.object(state, "now", lambda: NOW),
                        mock.patch.object(fast.tracker, "load_or_warn", lambda: [])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def last_run(self, beds_min=None, nuv_min=None):
        for f, m in ((self.bf, beds_min), (self.nf, nuv_min)):
            f.write_text(json.dumps({} if m is None else
                                    {"last_run": state.iso(NOW - dt.timedelta(minutes=m))}))

    def fast_run(self, **kw):
        out = io.StringIO()
        with mock.patch.object(fast.beds, "run", return_value=True) as b, \
                mock.patch.object(fast.nuvolau, "run", return_value=True) as n, \
                contextlib.redirect_stdout(out):
            fast.run(fast.Notifier(dry_run=True), **kw)
        return b.called, n.called, out.getvalue()

    # Null: nothing ran recently -> a backup run does everything.
    def test_backup_runs_when_nothing_recent(self):
        self.last_run(beds_min=40, nuv_min=40)
        self.assertEqual(self.fast_run(schedule="*/15 * * * *")[:2], (True, True))
        self.last_run()  # never ran
        self.assertEqual(self.fast_run(schedule="*/15 * * * *")[:2], (True, True))

    # Effect: external run 3 min ago -> backup skips both parts.
    def test_backup_skips_after_recent_external_run(self):
        self.last_run(beds_min=3, nuv_min=3)
        b, n, out = self.fast_run(schedule="*/15 * * * *")
        self.assertEqual((b, n), (False, False))
        self.assertIn("skipped hut checks: backup schedule", out)

    def test_backup_skips_only_the_recent_part(self):
        # Dec-Feb: Nuvolau ran 2 min ago (5-min tick), other huts 14 min ago.
        self.last_run(beds_min=14, nuv_min=2)
        self.assertEqual(self.fast_run(schedule="*/15 * * * *")[:2], (True, False))

    def test_external_and_manual_runs_never_skip(self):
        self.last_run(beds_min=1, nuv_min=1)
        self.assertEqual(self.fast_run(schedule="")[:2], (True, True))
        self.assertEqual(self.fast_run(schedule="", scope="nuvolau")[:2], (False, True))

    def test_pages_backup_guard(self):
        n = fast.Notifier(dry_run=True)
        self.pf.write_text(json.dumps({"last_run": {"at": state.iso(NOW - dt.timedelta(minutes=60))}}))
        with mock.patch.object(pagewatch, "PAGES", []), contextlib.redirect_stdout(io.StringIO()) as out:
            pagewatch.run(n, schedule="17 */4 * * *")
        self.assertIn("skipped page checks: backup schedule", out.getvalue())
        self.assertEqual(json.loads(self.pf.read_text())["last_run"]["at"],
                         state.iso(NOW - dt.timedelta(minutes=60)))  # untouched
        self.pf.write_text(json.dumps({"last_run": {"at": state.iso(NOW - dt.timedelta(minutes=300))}}))
        with mock.patch.object(pagewatch, "PAGES", []), contextlib.redirect_stdout(io.StringIO()) as out:
            pagewatch.run(n, schedule="17 */4 * * *")
        self.assertNotIn("skipped", out.getvalue())
        self.assertEqual(json.loads(self.pf.read_text())["last_run"]["at"], state.iso(NOW))


class SetupTriggers(unittest.TestCase):
    def setUp(self):
        self.m = load_setup()

    def workflow(self, name):
        return (ROOT / ".github/workflows" / name).read_text()

    def test_jobs_target_dispatchable_workflows_with_declared_inputs(self):
        for title, wf, inputs, _ in self.m.JOBS:
            text = self.workflow(wf)
            self.assertIn("workflow_dispatch:", text, wf)
            for k, v in inputs.items():
                self.assertRegex(text, rf"\n      {k}:\n", f"{wf} lacks input {k}")
                self.assertIn(v, text)
            self.assertTrue(title.startswith(self.m.PREFIX))

    def test_schedules_are_valid_and_dont_overlap(self):
        self.assertFalse(set(self.m.FULL_MIN) & set(self.m.NUV_MIN))
        self.assertEqual(sorted(self.m.FULL_MIN + self.m.NUV_MIN), list(range(3, 60, 5)))
        limits = {"minutes": (0, 59), "hours": (0, 23), "mdays": (1, 31), "months": (1, 12), "wdays": (0, 6)}
        for title, _, _, s in self.m.JOBS:
            for k, (lo, hi) in limits.items():
                vals = s[k]
                self.assertTrue(vals == [-1] or all(lo <= v <= hi for v in vals), (title, k))
            exp = dt.datetime.strptime(str(s["expiresAt"]), "%Y%m%d%H%M%S")
            self.assertTrue(dt.datetime(2026, 11, 9) < exp <= dt.datetime(2027, 6, 30), title)

    def test_nuvolau_5min_window_is_15_dec_to_15_feb(self):
        days = set()
        for title, _, inputs, s in self.m.JOBS:
            if inputs.get("scope") != "nuvolau":
                continue
            mdays = range(1, 32) if s["mdays"] == [-1] else s["mdays"]
            days |= {(mo, d) for mo in s["months"] for d in mdays}
        want = {(12, d) for d in range(15, 32)} | {(1, d) for d in range(1, 32)} | {(2, d) for d in range(1, 16)}
        self.assertEqual(days, want)

    def test_dense_starts_cover_the_window_every_3h(self):
        starts = []
        for _, wf, _, s in self.m.JOBS:
            if wf != "nuvolau-dense.yml":
                continue
            year = {1: 2027, 2: 2027}
            for mo in s["months"]:
                for d in s["mdays"]:
                    for h in s["hours"]:
                        starts.append(dt.datetime(year[mo], mo, d, h, s["minutes"][0], tzinfo=dt.timezone.utc))
        starts.sort()
        self.assertEqual(starts[0], nuvolau.DENSE_START)
        self.assertEqual(starts[-1] + dt.timedelta(hours=3), nuvolau.DENSE_END)
        self.assertTrue(all(b - a == dt.timedelta(hours=3) for a, b in zip(starts, starts[1:])))

    def test_job_body_keeps_token_out_of_title_url_and_body(self):
        tok = "github_pat_SENTINEL123"
        for title, wf, inputs, s in self.m.JOBS:
            j = self.m.job_body(title, wf, inputs, s, tok)
            self.assertNotIn(tok, j["title"] + j["url"] + j["extendedData"]["body"])
            self.assertEqual(j["extendedData"]["headers"]["Authorization"], f"Bearer {tok}")
            self.assertEqual(j["requestMethod"], 1)
            self.assertFalse(j["saveResponses"])
            body = json.loads(j["extendedData"]["body"])
            self.assertEqual(body["ref"], "main")
            self.assertTrue(re.fullmatch(rf"https://api\.github\.com/repos/frhl/dolomites-hut-watch/actions/workflows/{re.escape(wf)}/dispatches", j["url"]))


if __name__ == "__main__":
    unittest.main()
