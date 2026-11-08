# dolomites-hut-watch

Personal monitor for Alta Via 1 hut beds, summer 2027, 2 guests. **Alert only**: it never
books, submits booking/enquiry forms or pays. Every request uses an honest User-Agent
(`hutwatch/http.py`), a 20 s timeout and no retries; nothing tries to get past bot protection.

What each hut is checked with, and which huts fall back to page-change detection: [STATUS.md](STATUS.md).

## Where the checks run

| Runner | Schedule | Watches |
|---|---|---|
| `page-watch` (`pages.yml`) | every 4 h | 28 Jun: Pian de Fontana (preferred) + Pramperet (fallback), bookings opening. Change-watch for huts with no queryable engine (Sennes, Muntagnoles, Cinque Torri, Capanna Alpina). |
| `cancellation-watch` (`beds.yml`) | every 15 min; Nuvolau also every 5 min from 15 Dec to 15 Feb | Beds for 2 on 22 Jun (Biella) and 23 Jun (Lagazuoi, Scotoni, Col Gallina, Averau, Scoiattoli); Rifugio Nuvolau opening watch + beds on 24 and 23 Jun. |
| `nuvolau-dense` (`nuvolau-dense.yml`) | 31 Jan 21:00 UTC to 3 Feb 00:00 UTC | Nuvolau booking form probed **once a minute** (last year's June stage opened on 1 Feb). Shares the OPENING lock, so only one OPENING alert is ever sent. |
| Your Mac (launchd, `scripts/local_check.sh`) | at most hourly | 22 Jun: Fanes, Lavarella, Pederü, Fodara Vedla. Their booking API (Booking Südtirol) refuses GitHub's servers, so these run from your own connection. ntfy alerts only. |

**GitHub can delay scheduled runs by 10 to 30 minutes at busy times** (and sometimes skips
runs). "Every 5/15 min" is best effort. For Nuvolau, whose beds go within minutes, the
**ANNOUNCEMENT** alert (the published opening date and time) is the one that matters: it
lets you be online at that moment instead of relying on the OPENING alert arriving in time.

## Alerts

| Title | When | Where |
|---|---|---|
| `BEDS: <hut> <night>` | Beds for 2 available, any room type. If they are only in different rooms, the push starts `SPLIT across rooms:` and the issue says so. | ntfy p4 (tap opens booking page, call button), Telegram, issue. Re-alert every 2 h while available; one `GONE:` push when they go. |
| `ANNOUNCEMENT: Nuvolau 2027 booking` | Nuvolau pages announce the opening date/time | ntfy p5 if a date/time is in the text (else p4), issue with the matched text |
| `NUVOLAU 2027 BOOKING IS OPEN` | Nuvolau's booking calendar goes live for any date | ntfy p5 (urgent) x3, 1 min apart, tap opens the booking form; issue |
| `OPEN: <hut> 2027 bookings` | 28 Jun huts: page mentions 2027 with booking language (negatives like "non ancora" ignored) or the CAI booking calendar appears | ntfy p4 with an **Email hut** button (pre-filled booking email; add your name), issue if on |
| `CHANGE: <hut> page` | Booking-relevant text changed | ntfy p3 (Nuvolau p2), issue with before/after diff if on |
| `FAILING: ...` | 3 consecutive failures of any check | ntfy p3, issue if on; "Recovered" note later (issue only) |

Every alert goes to ntfy. GitHub issues are **off** (repository variable `HUTWATCH_ISSUES=off`,
because the repo is public); with it unset, each alert also opens or comments on one issue per
hut and event type. With issues off, run logs record only an alert's title, never its body.

## Setup

1. **ntfy**: secret `NTFY_TOPIC` = the topic your phones subscribe to. The topic is the only
   protection (anyone who knows it can read and post), so it is never written to logs, issues
   or state (`hutwatch/redact.py`, `tests/test_no_secret_leaks.py`).
2. **Telegram (optional)**: secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. **Test**: `gh workflow run beds.yml -f test_alert=true` sends one push per type
   (ANNOUNCEMENT p5, OPENING p5, BEDS p4) and opens a `TEST:` issue.
4. **Mac check** (Booking Südtirol huts), one line, asks for the topic (input hidden):
   ```bash
   ~/Projects/dolomites/tracker/scripts/install_launchd.sh
   ```
   Log: `~/Library/Logs/hutwatch-local.log`. Remove: `scripts/install_launchd.sh --uninstall`.
   It runs only while the Mac is awake and online; 3 failed hours in a row (e.g. offline)
   give a `FAILING` push. It pulls the repo before each run if the clone has no local edits,
   so tracker updates reach it.

## Tracker

The repo holds a **sanitized** copy, `AV1-booking-tracker.xlsx`: sheet `Nights`, columns
Night / Plan / Backup / Place / Status / Phone, only the nights the watches use. Make it
from your full tracker and commit it:

```bash
python3 scripts/sanitize_tracker.py ~/Downloads/AV1-booking-tracker.xlsx
git commit -am "Update tracker" && git push
```

- Mark **any** place for a night `Booked` and that night stops being checked by every watch.
  For Nuvolau, 23 and 24 Jun stop independently. To book a fallback but keep chasing the
  preferred hut, use another status (e.g. "Holding").
- The tracker's `Phone` for that hut and night goes into the BEDS push.
- Huts are matched by name (accents/case ignored): `aliases` in `hutwatch/beds_config.py`.
- If the tracker can't be read, everything is checked and a `FAILING: tracker unreadable` alert is raised.

## Stopping

- A night stops once it has passed (Europe/Rome; the night itself is still checked) or is Booked.
  When no night is left, `cancellation-watch` disables itself (`gh workflow enable beds.yml` to undo).
- `page-watch` stops and disables itself after 2027-06-28; `nuvolau-dense` does nothing outside its window.

## Adding a hut or night

Add a `BedHut(Hut(...))` to `hutwatch/beds_config.py` using an existing engine
(`fanes_family`, `planyo`, `disponibilita_php`, `bukly`, `scoiattoli_booking`, `nuvolau`), e.g.
Rifugio Tissi works with `disponibilita_php` and `params={"url": "https://www.rifugiotissi.com/EN/disponibilita.php"}`.

## State

`state/*.json` is committed back by the workflows (hashes and extracted sentences for diffs,
last results, failure counters, alert times, the Nuvolau OPENING lock). Page-watch commits
every run, which also keeps scheduled workflows from being auto-disabled after 60 days.
The Mac job keeps its state in `~/Library/Application Support/hutwatch/`.

## Local use

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m hutwatch pages --dry-run              # print alerts instead of sending
python -m hutwatch fast --dry-run --only fanes nuvolau
python -m hutwatch dense --dry-run --minutes 2  # 1-min Nuvolau probe, ignoring the date window
```

## Actions minutes

Each job is billed as at least 1 minute on a **private** repo: ~96 cancellation runs/day,
+192/day of 5-min Nuvolau ticks from 15 Dec to 15 Feb, ~51 h of dense probing around 1 Feb,
and the page watch. That is far beyond the Free plan's 2,000 included minutes; when they run
out, private-repo workflows stop until the next month. Standard GitHub-hosted runners are
free for **public** repos.
