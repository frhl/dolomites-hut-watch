"""Entry point for .github/workflows/beds.yml: cancellation watch + Nuvolau watch.

Runs are started by an external scheduler (cron-job.org, set up by
scripts/setup_triggers.py) through workflow_dispatch: every 15 min with scope=all, plus
every 5 min from 15 Dec to 15 Feb with scope=nuvolau (Nuvolau only, so the other huts
stay at 15 min). GitHub's own cron in beds.yml is only a backup: GitHub drops most
scheduled runs, and a backup run that arrives soon after an external one does nothing.
"""

from __future__ import annotations

import os

from . import beds, nuvolau, state, tracker
from .notify import Notifier
from .redact import log, plog

# A backup (GitHub cron) run skips a part that ran this recently.
BACKUP_GAP_MIN = 10


def _ran_within(path, minutes: float) -> bool:
    ago = state.minutes_since(state.load(path).get("last_run"))
    return ago is not None and 0 <= ago < minutes


def send_tests(notifier: Notifier) -> None:
    """One ntfy push per alert type, plus one issue saying what was sent."""
    lag = "https://rifugiolagazuoi.com/EN/disponibilita.php"
    sent = {
        "ANNOUNCEMENT": notifier.ntfy(
            "TEST ANNOUNCEMENT: Nuvolau 2027 booking",
            'When: 15 gennaio 2027, ore 9:00. "Test: prenotazioni 2027 dal 15 gennaio alle ore 9:00"',
            priority=5, click=nuvolau.ANNOUNCE_PAGES[0], tags=["loudspeaker", "test_tube"]),
        "OPENING": notifier.ntfy(
            f"TEST: {nuvolau.OPENING_TITLE}", "Test only (the real alert repeats 3x, 1 min apart).",
            priority=5, click=nuvolau.HUT.booking_url, phone=nuvolau.HUT.phone,
            tags=["rotating_light", "test_tube"]),
        "BEDS": notifier.ntfy(
            "TEST BEDS: Rifugio Lagazuoi 23 Jun 2027", "Test only: 2 dorm beds | Phone +39 340 719 5306",
            priority=4, click=lag, phone="+39 340 719 5306", tags=["bed", "test_tube"]),
    }
    notifier.telegram("TEST: hut monitor alerts (ANNOUNCEMENT, OPENING, BEDS) work.")
    notifier.issue("TEST: cancellation watch alerts",
                   "Manual test run. ntfy pushes accepted by the server: "
                   + ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in sent.items())
                   + ("" if notifier.ntfy_topic else "\n\n**NTFY_TOPIC secret is not set.**"))
    log("test pushes:", sent)


def run(notifier: Notifier, test_alert: bool = False, schedule: str | None = None,
        only: set[str] | None = None, scope: str | None = None) -> int:
    """schedule: GitHub's cron string ($SCHEDULE) when started by GitHub's own (backup)
    schedule, empty otherwise. scope: "all" (default) or "nuvolau" ($SCOPE)."""
    schedule = (schedule if schedule is not None else os.environ.get("SCHEDULE", "")).strip()
    scope = (scope if scope is not None else os.environ.get("SCOPE", "")).strip() or "all"
    if test_alert:
        send_tests(notifier)
    beds_due = scope != "nuvolau"
    nuv_due = not only or "nuvolau" in only
    if schedule:  # backup run: skip what the external trigger just did
        if beds_due and _ran_within(beds.STATE_FILE, BACKUP_GAP_MIN):
            beds_due = False
            plog(f"skipped hut checks: backup schedule, last run under {BACKUP_GAP_MIN} min ago")
        if nuv_due and _ran_within(nuvolau.STATE_FILE, BACKUP_GAP_MIN):
            nuv_due = False
            plog(f"skipped Nuvolau checks: backup schedule, last run under {BACKUP_GAP_MIN} min ago")
    rows = tracker.load_or_warn() if beds_due or nuv_due else []
    any_beds = beds.run(notifier, only=only, rows=rows) if beds_due else True
    any_nuv = nuvolau.run(notifier, rows=rows) if nuv_due else True
    if not any_beds and not any_nuv:
        log("No night left to watch.")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("all_done=true\n")
    for e in notifier.errors:
        log("ERROR:", e)
    return 1 if notifier.errors else 0
