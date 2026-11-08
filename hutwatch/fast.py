"""Entry point for .github/workflows/beds.yml: cancellation watch + Nuvolau watch.

The workflow fires every 15 min all year, plus extra 5-min ticks 15 Dec - 31 Jan.
The extra ticks run only the Nuvolau checks, so the other huts stay at 15 min.
"""

from __future__ import annotations

import os

from . import beds, nuvolau, tracker
from .notify import Notifier
from .redact import log

FULL_TICK = "*/15 * * * *"  # must match the first cron line in beds.yml


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
        only: set[str] | None = None) -> int:
    schedule = (schedule if schedule is not None else os.environ.get("SCHEDULE", "")).strip()
    if test_alert:
        send_tests(notifier)
    rows = tracker.load_or_warn()
    beds_due = schedule in ("", FULL_TICK)  # manual run or the 15-min tick
    any_beds = beds.run(notifier, only=only, rows=rows) if beds_due else True
    any_nuv = nuvolau.run(notifier, rows=rows) if not only or "nuvolau" in only else True
    if not any_beds and not any_nuv:
        log("No night left to watch.")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("all_done=true\n")
    for e in notifier.errors:
        log("ERROR:", e)
    return 1 if notifier.errors else 0
