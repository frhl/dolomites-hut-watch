"""Rifugio Nuvolau: 2027 booking-opening watch + beds on 24 (and 23) June 2027.

Three alerts:
  ANNOUNCEMENT  text on the hut's pages announcing the opening date/time (push p5 when a
                date or time is given, p4 otherwise)
  OPENING       the 2027 booking calendar goes live for any date: push p5
                "NUVOLAU 2027 BOOKING IS OPEN", repeated 3x, 1 min apart (once)
  BEDS          2 places on 24 or 23 June: same logic as the cancellation watch
Runs every 5 min 15 Dec - 31 Jan, every 15 min otherwise (.github/workflows/beds.yml).
"""

from __future__ import annotations

import datetime as dt
import importlib
import time

from . import beds, detect, http, state, tracker
from .beds_config import GUESTS, BedHut, BedNight
from .engines.base import Hut
from .extract import extract
from .notify import Notifier
from .redact import log, plog, reason

STATE_FILE = state.STATE_DIR / "nuvolau.json"
OPENING_FILE = state.STATE_DIR / "nuvolau_opening.json"
DENSE_FILE = state.STATE_DIR / "nuvolau_dense.json"   # written every dense run (uniform commits)
FAIL_THRESHOLD = 3
OPENING_TITLE = "NUVOLAU 2027 BOOKING IS OPEN"
OPENING_REPEATS = 3
OPENING_GAP_S = 60

# VikBooking (WordPress plugin) on the hut's own site; see STATUS.md.
HUT = Hut(id="nuvolau", name="Rifugio Nuvolau", engine="nuvolau",
          booking_url="https://rifugionuvolau.it/en/booking-form/",
          params={"form_url": "https://rifugionuvolau.it/en/booking-form/",
                  "availability_url": "https://rifugionuvolau.it/en/availability/",
                  "room_ids": [4, 6, 8, 5, 7],
                  "room_units": {"4": 3, "6": 4, "8": 4, "5": 5, "7": 8},
                  "probe_month": "2027-06"},
          phone="+39 0436 867938", email="info@rifugionuvolau.it")
ALIASES = ["Nuvolau"]
NIGHTS = [BedNight(dt.date(2027, 6, 24), [BedHut(HUT, ALIASES)]),
          BedNight(dt.date(2027, 6, 23), [BedHut(HUT, ALIASES)])]
# Homepages carry the "Prenotazioni 2027" block and the embedded Instagram feed (where
# last year's staged opening dates were announced); /dormire/ is the IT booking info page.
# The booking form itself is fetched by the OPENING check every run.
ANNOUNCE_PAGES: list[str] = [
    "https://rifugionuvolau.it/",
    "https://rifugionuvolau.it/en/",
    "https://rifugionuvolau.it/dormire/",
]

sleep = time.sleep  # patched in tests


def _engine():
    return importlib.import_module(f"hutwatch.engines.{HUT.engine}")


def _memo_fetch():
    """One request per distinct URL+params per run (form and calendar are shared by the
    OPENING check and both nights' BEDS checks). Errors are cached too: no retries."""
    cache: dict = {}

    def fetch(method, url, **kw):
        key = (method.upper(), url, repr(sorted((k, repr(v)) for k, v in kw.items())))
        if key not in cache:
            try:
                cache[key] = http.request(method, url, **kw)
            except Exception as e:  # noqa: BLE001
                cache[key] = e
        if isinstance(cache[key], Exception):
            raise cache[key]
        return cache[key]
    return fetch


def _issue(notifier: Notifier, title: str, body: str, **kw) -> bool:
    try:
        notifier.issue(title, body, **kw)
        return True
    except Exception as e:  # noqa: BLE001
        notifier.errors.append(f"issue '{title}' failed: {e}")
        return False


def _fail(rec: dict, err: Exception, what: str, url: str, notifier: Notifier) -> None:
    n = rec.get("consecutive_failures", 0) + 1
    rec.update(consecutive_failures=n, last_error=str(err)[:500])
    if n >= FAIL_THRESHOLD and not rec.get("failure_alerted"):
        title = f"FAILING: Nuvolau {what}"
        body = f"{what} failed {n} runs in a row ({url}).\n\nLast error: `{str(err)[:500]}`"
        notifier.ntfy(title, f"{what} failed {n}x: {str(err)[:200]}", priority=3, click=url, tags=["warning"])
        _issue(notifier, title, body)
        rec["failure_alerted"] = True


def _ok(rec: dict, what: str, notifier: Notifier) -> None:
    if rec.get("failure_alerted"):
        _issue(notifier, f"FAILING: Nuvolau {what}", "Recovered: works again.", comment_only=True)
    rec.update(consecutive_failures=0, failure_alerted=False, last_error=None)


def check_announcements(st: dict, notifier: Notifier, summary: list[str]) -> None:
    pages = st.setdefault("pages", {})
    pushed_this_run: set[str] = set()  # the IT homepage and /dormire/ carry the same block
    for url in ANNOUNCE_PAGES:
        rec = pages.setdefault(url, {})
        first = "hash" not in rec
        try:
            ex = extract(http.request("GET", url).text())
            if len(ex.text) < 50:
                raise http.FetchError(f"page returned almost no text ({len(ex.text)} chars)")
        except Exception as e:  # noqa: BLE001
            _fail(rec, e, "announcement watch", url, notifier)
            summary.append(f"announce {url}: ERROR {e}")
            plog(f"checked Nuvolau page {url}: FAIL ({reason(e)})")
            continue
        _ok(rec, "announcement watch", notifier)

        matches = detect.announcement_matches(ex.sentences)
        fresh = [m for m in matches if m not in rec.get("matches", []) and m not in pushed_this_run]
        pushed_this_run.update(fresh)
        if fresh:
            whens = [w for m in fresh for w in detect.when_mentions(m)]
            # First run = baseline of text already on the page (e.g. old Instagram posts): quiet.
            prio = 3 if first else (5 if whens else 4)
            when_txt = ", ".join(whens) if whens else "no exact date/time in the text"
            pushed = notifier.ntfy("ANNOUNCEMENT: Nuvolau 2027 booking", f"When: {when_txt}. \"{fresh[0][:300]}\"",
                          priority=prio, click=url, tags=["loudspeaker"])
            notifier.telegram(f"ANNOUNCEMENT: Nuvolau 2027 booking\nWhen: {when_txt}\n{url}")
            recorded = _issue(notifier, "ANNOUNCEMENT: Nuvolau 2027 booking opening",
                           f"**Page:** {url}\n\n**Announced date/time:** {when_txt}\n\n"
                           + "\n".join(f"> {m}" for m in fresh)
                           + ("\n\n_First run: this is the text already on the page._" if first else "")
                           + f"\n\n**Booking page:** {HUT.booking_url}")
            if not (pushed or recorded):  # nothing delivered -> keep old matches, fire again next run
                matches = rec.get("matches", [])
        rec["matches"] = matches

        relevant = detect.relevant_sentences(ex.sentences)
        h = detect.digest(relevant)
        if not first and rec.get("hash") != h:
            notifier.ntfy("CHANGE: Nuvolau page", f"Booking-relevant text changed on {url}",
                          priority=2, click=url, tags=["pencil"])
            _issue(notifier, "CHANGE: Nuvolau page",
                           f"**Page:** {url}\n\n```diff\n{detect.diff(rec.get('sentences', []), relevant)}\n```")
        rec["hash"], rec["sentences"] = h, relevant
        summary.append(f"announce {url}: ok, {len(matches)} announcement sentence(s)")
        plog(f"checked Nuvolau page {url}: ok")


OPENING_ISSUE = "OPENING: Nuvolau 2027 booking is open"


def opening_lock() -> dict:
    """Shared 'OPENING already alerted' record, used by the 5/15-min ticks and the dense job."""
    return state.load(OPENING_FILE)


def already_alerted(notifier: Notifier) -> str | None:
    lock = opening_lock()
    if lock.get("alerted"):
        return f"already alerted at {lock.get('alerted_at')} ({lock.get('by', '?')})"
    if notifier.issue_exists(OPENING_ISSUE):  # the other workflow fired after our checkout
        return "already alerted (open OPENING issue exists)"
    return None


def fire_opening(notifier: Notifier, detail: str, by: str) -> bool:
    """OPENING alert: urgent push x3, 1 min apart, + Telegram + issue. True if delivered.
    The repeats use ntfy's scheduled delivery, so the job doesn't run longer (a public run
    taking 2 extra minutes would itself give the opening away)."""
    pushed = 0
    for i in range(OPENING_REPEATS):
        pushed += notifier.ntfy(OPENING_TITLE, f"{detail}. Book now: {HUT.booking_url}"
                                + (f" | Phone {HUT.phone}" if HUT.phone else ""),
                                priority=5, click=HUT.booking_url, phone=HUT.phone, tags=["rotating_light"],
                                delay=f"{i * OPENING_GAP_S}s" if i else None)
    notifier.telegram(f"{OPENING_TITLE}\n{HUT.booking_url}")
    recorded = _issue(notifier, OPENING_ISSUE,
                      f"The 2027 booking calendar is live: {detail}\n\n**Book:** {HUT.booking_url}\n\n"
                      f"Target nights: 24 Jun 2027 (and 23 Jun), {GUESTS} guests.\n\n"
                      "_Alert only: nothing was booked, submitted or paid._")
    if pushed or recorded:  # nothing delivered -> try again next run
        state.save(OPENING_FILE, {"alerted": True, "alerted_at": state.iso(state.now()),
                                  "by": by, "pushes_delivered": pushed, "detail": detail[:300]})
        return True
    return False


def check_opening(st: dict, notifier: Notifier, summary: list[str], fetch=None) -> bool:
    """Always probes (also after the alert), so requests, timing and logs look the same
    before and after opening day."""
    rec = st.setdefault("opening", {})
    done = already_alerted(notifier)
    try:
        is_open, detail = _engine().booking_open(HUT, fetch or http.request)
    except Exception as e:  # noqa: BLE001
        _fail(rec, e, "opening check", HUT.booking_url, notifier)
        summary.append(f"opening: ERROR {e}")
        plog(f"checked Nuvolau booking form: FAIL ({reason(e)})")
        return bool(done)
    _ok(rec, "opening check", notifier)
    plog("checked Nuvolau booking form: ok")
    rec["last_detail"] = detail[:300]
    summary.append(f"opening: {'OPEN' if is_open else 'not open'} ({detail})" + (f"; {done}" if done else ""))
    if done:
        return True
    if not is_open:
        if "imminent" in detail and not rec.get("imminent_alerted"):
            notifier.ntfy("NUVOLAU: opening looks imminent", detail[:300], priority=4,
                          click=HUT.booking_url, tags=["hourglass"])
            _issue(notifier, "PRE-OPENING: Nuvolau 2027 booking",
                   f"Not open yet, but: {detail}\n\nBooking page: {HUT.booking_url}")
            rec["imminent_alerted"] = True
        return False
    fire_opening(notifier, detail, by="tick")
    return True


# ---------------- dense probe around 1 February ----------------

# Last year the June stage opened on 1 Feb. During this window a long-running job probes
# the booking form once a minute (1 request) instead of relying on 5-min cron ticks.
DENSE_START = dt.datetime(2027, 1, 31, 21, 0, tzinfo=dt.timezone.utc)   # 22:00 Rome
DENSE_END = dt.datetime(2027, 2, 3, 0, 0, tzinfo=dt.timezone.utc)       # 01:00 Rome, 3 Feb
DENSE_BLOCK = dt.timedelta(minutes=175)   # one job per 3-h cron slot
DENSE_INTERVAL_S = 60
monotonic = time.monotonic  # patched in tests


def dense(notifier: Notifier, minutes: float | None = None, rows=...) -> int:
    """Probe the booking form every DENSE_INTERVAL_S until the block or window ends.
    Keeps probing after an alert (never re-alerting) so the job looks the same either way.
    `minutes` (manual test runs) ignores the window and limits the loop."""
    now = state.now()
    if minutes is None and not (DENSE_START <= now < DENSE_END):
        plog("checked Nuvolau booking form: not in the dense window, nothing to do")
        return 0
    if rows is ...:
        rows = tracker.load_or_warn()
    active, notes = beds.active_nights(NIGHTS, rows, state.today_rome())
    if not active:
        plog("checked Nuvolau booking form: no Nuvolau night left, nothing to do")
        return 0
    span = dt.timedelta(minutes=minutes) if minutes is not None else min(DENSE_BLOCK, DENSE_END - now)
    deadline = monotonic() + span.total_seconds()
    p = _engine()._params(HUT)
    probes = fails = 0
    while True:
        probes += 1
        try:
            form = _engine().fetch_form(http.request, p)
        except Exception as e:  # noqa: BLE001 - the 5/15-min ticks own the FAILING alert
            fails += 1
            log(f"dense probe {probes}: ERROR {e}")
        else:
            if form.enabled and not already_alerted(notifier):
                fire_opening(notifier, "booking form is live (dense probe)", by="dense")
                log(f"dense probe {probes}: OPEN, alert sent")
            elif probes == 1 or probes % 30 == 0:
                log(f"dense probe {probes}: {'live' if form.enabled else 'still disabled'}")
        if monotonic() + DENSE_INTERVAL_S >= deadline:
            break
        sleep(DENSE_INTERVAL_S)
    plog(f"checked Nuvolau booking form {probes} times: {probes - fails} ok, {fails} failed")
    state.save(DENSE_FILE, {"last_run": state.iso(state.now()), "probes": probes, "failed": fails})
    return 0


def run(notifier: Notifier, rows=...) -> bool:
    """Returns True while at least one Nuvolau night is still being watched."""
    today = state.today_rome()
    if rows is ...:
        rows = tracker.load_or_warn()
    active, summary = beds.active_nights(NIGHTS, rows, today)
    if not active:
        beds.write_summary("Nuvolau", summary + ["Nuvolau: no active night, nothing checked"])
        plog("checked Nuvolau: no Nuvolau night left, nothing to do")
        return False
    st = state.load(STATE_FILE)
    fetch = _memo_fetch()
    check_opening(st, notifier, summary, fetch)
    check_announcements(st, notifier, summary)  # always, so runs look the same after opening
    table = list(beds.TABLE_HEAD)
    entries = st.setdefault("entries", {})
    now = state.now()
    for n in active:
        bh = n.huts[0]
        beds.process_hut(entries, bh.hut, n.night, beds.hut_phone(rows, n.night, bh),
                         lambda n=n: _engine().check(HUT, n.night, GUESTS, fetch),
                         notifier, now, table)
    live = {f"{n.night}/{HUT.id}" for n in active}
    for k in list(entries):
        if k not in live:
            entries.pop(k)
    st["last_run"] = state.iso(now)
    state.save(STATE_FILE, st)
    beds.write_summary("Nuvolau", summary + [""] + table)
    return True
