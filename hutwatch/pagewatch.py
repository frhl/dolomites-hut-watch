"""Slow page watch: OPEN (2027 booking language), CHANGE (booking-relevant text diff),
FAILING (3 consecutive fetch failures). Runs every 4 h from .github/workflows/pages.yml."""

from __future__ import annotations

import os
import urllib.parse

from . import detect, http, state, tracker
from .extract import extract
from .notify import Notifier
from .redact import log, plog, reason
from .pagewatch_config import EMAIL_BODY, EMAIL_SUBJECT, HUTS, PAGES, STOP_AFTER, hut

STATE_FILE = state.STATE_DIR / "pages.json"
FAIL_THRESHOLD = 3


def mailto_link(to: str) -> str:
    return f"mailto:{to}?" + urllib.parse.urlencode(
        {"subject": EMAIL_SUBJECT, "body": EMAIL_BODY}, quote_via=urllib.parse.quote)


def booking_email(to: str) -> str:
    mailto = mailto_link(to)
    return (
        "### Booking email (send it yourself)\n\n"
        f"**To:** {to}  \n**Subject:** {EMAIL_SUBJECT}\n\n"
        f"```text\n{EMAIL_BODY}\n```\n\n"
        f"[Open in mail app]({mailto})\n"
    )


def open_body(h, page, matches, markers) -> str:
    lines = [f"**Hut:** Rifugio {h.name} ({h.role.lower()} for {h.night:%a %d %b %Y})",
             f"**Page:** {page.label}: {page.url}", ""]
    if matches:
        lines += ["**Matched text:**", ""] + [f"> {m}" for m in matches] + [""]
    if markers:
        lines += ["**The booking calendar widget appeared on the page** "
                  "(it is absent while a hut is not bookable online). Markers:", ""]
        lines += [f"- `{m}`" for m in markers] + [""]
    if h.email_to:
        lines.append(booking_email(h.email_to))
    lines.append("_Alert only: nothing was booked, submitted or paid._")
    return "\n".join(lines)


# GitHub's own cron is a backup for the external trigger; it skips a run if one happened
# this recently (the external trigger runs every 4 h; GitHub's cron arrives hours late).
BACKUP_GAP_MIN = 210


def run(notifier: Notifier, test_alert: bool = False, schedule: str | None = None) -> int:
    today = state.today_rome()
    if today > STOP_AFTER:
        log(f"{today} is after {STOP_AFTER}: page watch finished, doing nothing.")
        return 0
    schedule = (schedule if schedule is not None else os.environ.get("SCHEDULE", "")).strip()
    if schedule and not test_alert:
        ago = state.minutes_since((state.load(STATE_FILE).get("last_run") or {}).get("at"))
        if ago is not None and 0 <= ago < BACKUP_GAP_MIN:
            plog(f"skipped page checks: backup schedule, last run under {BACKUP_GAP_MIN} min ago")
            return 0

    if test_alert:
        h = HUTS[0]
        notifier.ntfy("TEST: page watch alert", "Test push from the page watch (OPEN alerts look like this).",
                      priority=4, click=PAGES[0].url, tags=["tada", "test_tube"],
                      extra_actions=[{"action": "view", "label": "Email hut", "url": mailto_link(h.email_to)}])
        notifier.issue("TEST: page watch alert",
                       "Test alert from the page watch (manual run). If you got this, issue "
                       "alerts work.\n\n" + booking_email(h.email_to))
        notifier.telegram("TEST: hut page watch alert works.")

    rows = tracker.load_or_warn()
    st = state.load(STATE_FILE)
    pages_st: dict = st.setdefault("pages", {})
    t = state.iso(state.now())
    summary: list[str] = []

    for page in PAGES:
        h = hut(page.hut)
        if today > h.night:
            summary.append(f"{page.id}: skipped (night {h.night} passed)")
            plog(f"checked {page.id}: not checked (night no longer watched)")
            continue
        if rows is not None:
            booked = tracker.night_booked(rows, h.night)
            if booked:
                summary.append(f"{page.id}: skipped ({booked.place} marked Booked for {h.night})")
                plog(f"checked {page.id}: not checked (night no longer watched)")
                continue
        old = pages_st.get(page.id, {})
        new = dict(old)
        new["url"] = page.url
        new["last_checked"] = t
        events: list[tuple[str, str, bool]] = []  # (title, body, comment_only)

        try:
            resp = http.request("GET", page.url)
            ex = extract(resp.text())
            if len(ex.text) < 50:
                raise http.FetchError(f"page returned almost no text ({len(ex.text)} chars)")
        except Exception as e:  # noqa: BLE001 - any failure counts
            n = old.get("consecutive_failures", 0) + 1
            new.update(last_status=f"error: {e}", consecutive_failures=n)
            if n >= FAIL_THRESHOLD and not old.get("failure_alerted"):
                events.append((f"FAILING: {h.name} monitor",
                               f"**{page.label}** {page.url} failed {n} runs in a row.\n\n"
                               f"Last error: `{e}`\n\nThe monitor keeps trying every run.", False))
                new["failure_alerted"] = True
            summary.append(f"{page.id}: FAIL ({n}x) {e}")
            plog(f"checked {page.id}: FAIL ({reason(e)})")
        else:
            if old.get("failure_alerted"):
                events.append((f"FAILING: {h.name} monitor",
                               f"Recovered: {page.url} fetched OK again.", True))
            new.update(last_status=f"ok (HTTP {resp.status})", consecutive_failures=0,
                       failure_alerted=False, last_success=t)

            relevant = detect.relevant_sentences(ex.sentences)
            hsh = detect.digest(relevant)
            if old.get("hash") and old["hash"] != hsh:
                events.append((f"CHANGE: {h.name} page",
                               f"**Hut:** Rifugio {h.name}  \n**Page:** {page.label}: {page.url}\n\n"
                               "Booking-relevant text changed since the last run:\n\n"
                               f"```diff\n{detect.diff(old.get('sentences', []), relevant)}\n```", False))
                new["last_changed"] = t
            new["hash"], new["sentences"] = hsh, relevant

            if h.open_detection:
                matches = detect.open_matches(ex.sentences)
                fresh = [m for m in matches if m not in old.get("open_matches", [])]
                markers = ex.widget_markers if not old.get("widget_markers") else []
                if fresh or markers:
                    events.append((f"OPEN: {h.name} 2027 bookings",
                                   open_body(h, page, fresh, markers), False))
                new["open_matches"] = matches
            new["widget_markers"] = ex.widget_markers
            plog(f"checked {page.id}: ok")
            summary.append(f"{page.id}: ok, {len(relevant)} relevant sentences"
                           + (", CHANGED" if new.get("last_changed") == t else ""))

        delivered = True
        for title, body, comment_only in events:
            if not comment_only:
                # Push (the only channel when issues are off): short text + tap to the page;
                # OPEN alerts get an "Email hut" button pre-filled with the booking email.
                kind = title.split(":", 1)[0]
                first = next((ln[2:] for ln in body.splitlines() if ln.startswith("> ")), "")
                msg = (first or body.split("\n\n")[0]).replace("**", "")[:300]
                extra = ([{"action": "view", "label": "Email hut", "url": mailto_link(h.email_to)}]
                         if kind == "OPEN" and h.email_to else None)
                pushed = notifier.ntfy(title, msg, priority={"OPEN": 4}.get(kind, 3), click=page.url,
                                       tags={"OPEN": ["tada"], "CHANGE": ["pencil"]}.get(kind, ["warning"]),
                                       extra_actions=extra)
                if notifier.ntfy_topic and not pushed:
                    delivered = False
                notifier.telegram(f"{title}\n{page.url}")
            try:
                notifier.issue(title, body, comment_only=comment_only)
            except Exception as e:  # noqa: BLE001
                delivered = False
                notifier.errors.append(f"issue '{title}' failed: {e}")
        # Undelivered alert -> keep old detection state so it fires again next run.
        if delivered:
            pages_st[page.id] = new
        else:
            old = dict(old)
            old["last_status"] = new.get("last_status", "") + " (alert delivery failed)"
            pages_st[page.id] = old

    st["last_run"] = {"at": t, "summary": summary}
    state.save(STATE_FILE, st)
    log("\n".join(summary))
    for e in notifier.errors:
        log("ERROR:", e)
    return 1 if notifier.errors else 0
