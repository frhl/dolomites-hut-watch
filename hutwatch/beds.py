"""Fast cancellation watch: asks each hut's booking engine for 2 guests on the target
night. Runs from .github/workflows/beds.yml (every 15 min for these huts).

Per (night, hut), see process_hut():
  became available -> BEDS push (ntfy high priority) + Telegram + issue
  still available  -> re-alert every REALERT
  disappeared      -> one "gone" notice
  3 failures       -> FAILING alert (once), "recovered" note when it works again
"""

from __future__ import annotations

import datetime as dt
import importlib
import os
from typing import Callable

from . import http, state, tracker
from .beds_config import GUESTS, NIGHTS, BedHut, BedNight
from .engines.base import CheckResult, Hut, Status
from .notify import Notifier
from .redact import log, scrub

STATE_FILE = state.STATE_DIR / "beds.json"
FAIL_THRESHOLD = 3
REALERT = dt.timedelta(hours=2)
TABLE_HEAD = ["| Night | Hut | Result | Detail |", "|---|---|---|---|"]


def night_label(d: dt.date) -> str:
    return f"{d.day} {d:%b %Y}"


def check_one(bh: BedHut, night: dt.date) -> CheckResult:
    engine = importlib.import_module(f"hutwatch.engines.{bh.hut.engine}")
    return engine.check(bh.hut, night, GUESTS, http.request)


def active_nights(nights: list[BedNight], rows, today) -> tuple[list[BedNight], list[str]]:
    """Nights still to watch: not passed (the night itself is still checked) and nothing Booked."""
    active, notes = [], []
    for n in nights:
        if today > n.night:
            notes.append(f"{n.night}: date passed, not checking")
            continue
        if rows is not None:
            b = tracker.night_booked(rows, n.night)
            if b:
                notes.append(f"{n.night}: {b.place} is marked Booked, not checking")
                continue
        active.append(n)
    return active, notes


def tracker_health(st: dict, rows, notifier: Notifier, summary: list[str]) -> None:
    if rows is None:
        summary.append("WARNING: tracker unreadable, Booked statuses ignored")
        if not st.get("tracker_alerted"):
            try:
                notifier.issue("FAILING: tracker unreadable",
                               f"Could not read `{tracker.DEFAULT_PATH.name}` (sheet `{tracker.SHEET}`). "
                               "Every configured hut is checked regardless of Booked status until fixed.")
                st["tracker_alerted"] = True
            except Exception as e:  # noqa: BLE001
                notifier.errors.append(f"tracker alert failed: {e}")
    else:
        st.pop("tracker_alerted", None)


def hut_phone(rows, night: dt.date, bh: BedHut) -> str | None:
    row = tracker.find(rows, night, bh.aliases) if rows else None
    return (row.phone if row and row.phone else None) or bh.hut.phone


def process_hut(entries: dict, hut: Hut, night: dt.date, phone: str | None,
                check: Callable[[], CheckResult], notifier: Notifier, now: dt.datetime,
                table: list[str]) -> None:
    """Run one availability check and emit BEDS / GONE / FAILING events for it."""
    key = f"{night}/{hut.id}"
    old = entries.get(key, {})
    new = dict(old)
    events = []  # (kind, title, body, push_priority or None)
    name, nl = hut.name, night_label(night)
    res: CheckResult | None = None

    try:
        res = check()
        if res.status == Status.UNKNOWN:
            raise http.FetchError(f"unclassifiable response: {res.detail}")
    except Exception as e:  # noqa: BLE001 - any failure counts
        res = None
        cnt = old.get("consecutive_failures", 0) + 1
        new.update(consecutive_failures=cnt, last_error=str(e)[:500])
        if cnt >= FAIL_THRESHOLD and not old.get("failure_alerted"):
            new["failure_alerted"] = True
            events.append(("fail", f"FAILING: {name} checker",
                           f"The availability check for **{name}** ({nl}) failed {cnt} runs in a row.\n\n"
                           f"Last error: `{str(e)[:500]}`\n\nCheck manually: {hut.booking_url}", 3))
        table.append(f"| {night} | {name} | ERROR ({cnt}x) | {str(e)[:120]} |")
    else:
        if old.get("failure_alerted"):
            events.append(("recovered", f"FAILING: {name} checker", "Recovered: check works again.", None))
        new.update(consecutive_failures=0, failure_alerted=False, last_error=None)
        prev = old.get("status")
        split_note = (f"**Note: no single room/unit has {GUESTS} beds; the beds are in different "
                      "rooms (book separate beds, or phone).**\n\n") if res.split else ""
        body = (f"**{name}**, night of {night:%a} {night_label(night)} (check-in {night}, "
                f"check-out {night + dt.timedelta(days=1)}), {GUESTS} guests.\n\n"
                + split_note +
                f"**Result:** {res.detail or res.status.value}\n\n"
                + "".join(f"- {o}\n" for o in res.options)
                + f"\n**Book:** {hut.booking_url}\n"
                + (f"**Phone:** {phone}\n" if phone else "")
                + (f"**Email:** {hut.email}\n" if hut.email else "")
                + "\n_Alert only: nothing was booked, submitted or paid._")
        if res.status == Status.AVAILABLE:
            last = state.parse(old.get("last_alert"))
            if prev != Status.AVAILABLE.value:
                events.append(("beds", f"BEDS: {name} {nl}", body, 4))
                new["available_since"] = state.iso(now)
            elif last is None or now - last >= REALERT:
                events.append(("beds", f"BEDS: {name} {nl}", "Still available.\n\n" + body, 4))
        elif prev == Status.AVAILABLE.value:
            events.append(("gone", f"BEDS: {name} {nl}",
                           f"Gone: no longer available ({res.status.value}: {res.detail}).", 3))
            new["available_since"] = None
        new["status"] = res.status.value
        if res.status != Status.AVAILABLE or prev != Status.AVAILABLE.value:
            new["detail"] = res.detail[:300]
        table.append(f"| {night} | {name} | {res.status.value} | {res.detail[:120]} |")

    delivered = True
    for kind, title, body, prio in events:
        push_title = f"GONE: {name} {nl}" if kind == "gone" else title
        if prio is not None:
            if kind == "beds":
                msg = (("SPLIT across rooms: " if res and res.split else "")
                       + (res.detail if res and res.detail else f"Beds for {GUESTS}")
                       + (f" | Phone {phone}" if phone else ""))
            else:
                msg = body.split("\n\n")[0].replace("**", "")
            notifier.ntfy(push_title, msg, priority=prio, click=hut.booking_url,
                          phone=phone if kind == "beds" else None,
                          tags=["bed"] if kind == "beds" else ["warning"])
            notifier.telegram(f"{push_title}\n{hut.booking_url}" + (f"\nPhone: {phone}" if phone else ""))
        try:
            notifier.issue(title, body, comment_only=(kind == "recovered"))
        except Exception as e:  # noqa: BLE001
            delivered = False
            notifier.errors.append(f"issue '{title}' failed: {e}")
        if kind == "beds":
            new["last_alert"] = state.iso(now)
    # Undelivered issue -> keep old state so the event fires again next run.
    entries[key] = new if delivered else old


def write_summary(title: str, lines: list[str]) -> None:
    report = scrub("\n".join(lines))
    log(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"## {title}\n\n{report}\n\n")


def run(notifier: Notifier, only: set[str] | None = None, rows=..., ) -> bool:
    """Check every configured hut on every active night. Returns True if any night is active."""
    today = state.today_rome()
    if rows is ...:
        rows = tracker.load_or_warn()
    st = state.load(STATE_FILE)
    summary: list[str] = []
    tracker_health(st, rows, notifier, summary)
    active, notes = active_nights(NIGHTS, rows, today)
    summary += notes
    entries: dict = st.setdefault("entries", {})
    now = state.now()
    table = list(TABLE_HEAD)

    on_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    for n in active:
        for bh in n.huts:
            if only and bh.hut.id not in only:
                continue
            if on_ci and bh.hut.params.get("blocked_on_ci"):
                table.append(f"| {n.night} | {bh.hut.name} | SKIPPED | engine blocks GitHub runners (HTTP 403); "
                             "run locally, see STATUS.md |")
                entries.pop(f"{n.night}/{bh.hut.id}", None)
                continue
            process_hut(entries, bh.hut, n.night, hut_phone(rows, n.night, bh),
                        lambda bh=bh, n=n: check_one(bh, n.night), notifier, now, table)

    live = {f"{n.night}/{bh.hut.id}" for n in active for bh in n.huts
            if not (on_ci and bh.hut.params.get("blocked_on_ci"))}
    for k in list(entries):
        if k not in live:
            entries.pop(k)  # nights no longer watched
    state.save(STATE_FILE, st)
    write_summary("Cancellation watch", summary + ([""] + table if len(table) > 2 else []))
    return bool(active)
