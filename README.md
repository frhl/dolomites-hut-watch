# dolomites-hut-watch

Personal monitor for Alta Via 1 hut beds, summer 2027, 2 guests. **Alert only**: it never
books, submits booking/enquiry forms or pays. Every request uses an honest User-Agent
(`hutwatch/http.py`), a 20 s timeout and no retries; nothing tries to get past bot protection.

How each hut is checked: [CHECKERS.md](CHECKERS.md). Whether the checks are running:
[STATUS.md](STATUS.md) (run times and OK/FAILING only).

## What is public, what is private

This repo is public, so nothing in it, its Actions logs or its commit history reveals
availability:

- Run logs and job summaries print only `checked <hut>: ok | FAIL (<reason>)`.
- Results, page text, alert timers, failure details and the tracker live in the private repo
  `frhl/dolomites-hut-watch-state`, checked out at `./private` (git-ignored here) with a
  deploy key (secret `STATE_DEPLOY_KEY`). Every job commits there every run.
- The only public commit is page-watch's regenerated STATUS.md (every 4 h; also the
  keep-alive that stops GitHub disabling the schedules after 60 days). It depends only on run
  times and failure counters.
- GitHub issues are off (`HUTWATCH_ISSUES=off`); alerts go to ntfy only.
- `tests/test_public_output.py` checks that the public log, summary and STATUS.md are
  byte-identical whether huts are full or have beds (with every alert type firing).
- Alert-delivery errors don't turn a run red (that would give an alert away); undelivered
  alerts are retried next run and the error is written to `state/last_errors.json` (private).

## Where the checks run

| Runner | Schedule | Watches |
|---|---|---|
| `page-watch` (`pages.yml`) | every 4 h | 28 Jun: Pian de Fontana (preferred) + Pramperet (fallback), bookings opening. Change-watch for huts with no queryable engine (Sennes, Muntagnoles, Cinque Torri, Capanna Alpina). |
| `cancellation-watch` (`beds.yml`) | every 15 min; Nuvolau also every 5 min from 15 Dec to 15 Feb (started by cron-job.org, below) | Beds for 2 on 22 Jun (Biella) and 23 Jun (Lagazuoi, Scotoni, Col Gallina, Averau, Scoiattoli); Rifugio Nuvolau opening watch + beds on 24 and 23 Jun. |
| `nuvolau-dense` (`nuvolau-dense.yml`) | 31 Jan 21:00 UTC to 3 Feb 00:00 UTC | Nuvolau booking form probed **once a minute** (last year's June stage opened on 1 Feb). Shares the OPENING lock, so only one OPENING alert is ever sent. |
| Your Mac (launchd, `scripts/local_check.sh`) | at most hourly | 22 Jun: Fanes, Lavarella, Pederü, Fodara Vedla. Their booking API (Booking Südtirol) refuses GitHub's servers, so these run from your own connection. ntfy alerts only. |

### What starts the runs

GitHub's own `schedule:` is unreliable here: in its first day public, a 15-min cron fired
3 of ~74 times and the 4-h cron 2 of 5 (each 2.5-3.5 h late). So **cron-job.org** starts
the workflows instead, by calling GitHub's `workflow_dispatch` API on a precise schedule
(UTC); the checks still run on GitHub, unchanged:

| cron-job.org job | Starts |
|---|---|
| every 15 min (:03, :18, :33, :48) | `beds.yml`, scope `all` |
| every 5 min on the other slots, 15 Dec - 15 Feb | `beds.yml`, scope `nuvolau` (Nuvolau only) |
| every 4 h (00:23, 04:23, ...) | `pages.yml` |
| 31 Jan 21:00, then every 3 h on 1-2 Feb | `nuvolau-dense.yml` |

Set up with `python3 scripts/setup_triggers.py` (asks, hidden, for a cron-job.org API key
and a GitHub fine-grained token limited to this repo with "Actions: Read and write"; the
token is stored only in the cron-job.org jobs). `--status` shows each job's last result,
`--remove` deletes them. cron-job.org emails you if a job fails 3 times in a row.

GitHub's own crons stay as a backup. A backup run that arrives soon after an external
one skips (cancellation-watch: within 10 min; page-watch: within 3.5 h), so the huts don't
get extra requests.

Even so, a dispatched run takes ~30-60 s to start. For Nuvolau, whose beds go within
minutes, the **ANNOUNCEMENT** alert (the published opening date and time) is still the one
that matters: it lets you be online at that moment.

## Alerts

| Title | When | Where |
|---|---|---|
| `BEDS: <hut> <night>` | Beds for 2 available, any room type. If they are only in different rooms, the push starts `SPLIT across rooms:` and the issue says so. | ntfy p4 (tap opens booking page, call button), Telegram, issue. Re-alert every 2 h while available; one `GONE:` push when they go. |
| `ANNOUNCEMENT: Nuvolau 2027 booking` | Nuvolau pages announce the opening date/time | ntfy p5 if a date/time is in the text (else p4), issue with the matched text |
| `NUVOLAU 2027 BOOKING IS OPEN` | Nuvolau's booking calendar goes live for any date | ntfy p5 (urgent) x3, 1 min apart, tap opens the booking form; issue |
| `OPEN: <hut> 2027 bookings` | 28 Jun huts: page mentions 2027 with booking language (negatives like "non ancora" ignored) or the CAI booking calendar appears | ntfy p4 with an **Email hut** button (pre-filled booking email; add your name), issue if on |
| `IMPORTANT: <hut> page changed` | Booking-relevant text changed and the new text mentions 2027, says bookings are open or next season, gives a booking date, or a "not open yet" notice disappeared | ntfy p4. Text: why, then what they did (`«old» → «new»`, `New: …`, `Gone: …`). No extra push when an OPEN/ANNOUNCEMENT push already covers it. |
| `Not important: <hut> page changed` | Any other change: formatting fixes (same words) or other wording | ntfy p2 (quiet), same layout |
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
   It appears as **Dolomites Hut Watch** (System Settings > General > Login Items > Allow in
   the Background, and in Activity Monitor for ~10 s while a check runs): a small app in
   `~/Applications` whose launcher runs `scripts/local_check.sh`. launchd label
   `com.frhl.dolomites-hut-watch`. Log: `~/Library/Logs/dolomites-hut-watch.log`.
   Remove: `scripts/install_launchd.sh --uninstall`.
   It runs only while the Mac is awake and online; 3 failed hours in a row (e.g. offline)
   give a `FAILING` push. It pulls the repo before each run if the clone has no local edits,
   so tracker updates reach it.

## Tracker

`AV1-booking-tracker.xlsx` lives in the **private** state repo (sheet `Nights`: a header row
with `Night`, `Place`, `Status`, `Phone`; other columns and sheets are ignored). Replace it with
your working copy and push:

```bash
cp ~/Downloads/AV1-booking-tracker.xlsx ~/Projects/dolomites/tracker/private/
git -C ~/Projects/dolomites/tracker/private commit -am "Update tracker" && git -C ~/Projects/dolomites/tracker/private push
```

- Mark **any** place for a night `Booked` and that night stops being checked by every watch.
  For Nuvolau, 23 and 24 Jun stop independently. To book a fallback but keep chasing the
  preferred hut, use another status (e.g. "Holding").
- The tracker's `Phone` for that hut and night goes into the BEDS push.
- Huts are matched by name (accents/case ignored): `aliases` in `hutwatch/beds_config.py`.
- If the tracker can't be read, everything is checked and a `FAILING: tracker unreadable` push is sent.

## Stopping

- A night stops once it has passed (Europe/Rome; the night itself is still checked) or is Booked.
  When no night is left, `cancellation-watch` disables itself (`gh workflow enable beds.yml` to undo).
- `page-watch` stops and disables itself after 2027-06-28; `nuvolau-dense` does nothing outside its window.

## Adding a hut or night

Add a `BedHut(Hut(...))` to `hutwatch/beds_config.py` using an existing engine
(`fanes_family`, `planyo`, `disponibilita_php`, `bukly`, `scoiattoli_booking`, `nuvolau`), e.g.
Rifugio Tissi works with `disponibilita_php` and `params={"url": "https://www.rifugiotissi.com/EN/disponibilita.php"}`.

## State

In the private repo under `state/`: `pages.json`, `beds.json`, `nuvolau.json` (results,
extracted page text for diffs, failure counters, alert times), `nuvolau_opening.json`
(the shared OPENING lock), `nuvolau_dense.json`, `last_errors.json`. The Mac job keeps
its own state in `~/Library/Application Support/hutwatch/` and logs details locally.

## Local use

```bash
pip install -r requirements.txt
gh repo clone frhl/dolomites-hut-watch-state private   # state + tracker (private)
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
