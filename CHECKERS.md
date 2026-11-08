# How each hut is checked

All checks use the honest User-Agent in `hutwatch/http.py`, read-only requests (no carts,
holds, enquiry forms, personal data or payments) and nothing that gets around bot
protection. Results are never published: the public [STATUS.md](STATUS.md) shows only
whether each check ran and worked.

**Timing caveat:** GitHub can delay scheduled runs by 10 to 30 minutes at busy times (and
skip some). The 5- and 15-minute schedules are best effort. For Nuvolau, the ANNOUNCEMENT
alert (the published opening date/time) is the one that matters for being online on the day.

## Night of 22 June 2027 (check-in Tue 22, check-out Wed 23)

| Hut | Runs on | How |
|---|---|---|
| Rifugio Fanes | Mac, hourly | `fanes_family`: Booking Südtirol widget API, `GET api.widgets.bookingsuedtirol.com/v6/properties/13308/availabilities`, per-arrival-night rules, asked as one room for 2 and as two 1-person units (dorm beds). A single free night between bookings under a 2-night minimum is invisible to this API, so phoning can still find beds. |
| Rifugio Lavarella | Mac, hourly | `fanes_family`, property 13004 |
| Berggasthaus Pederü | Mac, hourly | `fanes_family`, property 10716 |
| Rifugio Fodara Vedla | Mac, hourly | `fanes_family`, property 12869 |
| Rifugio Sennes | page watch, 4 h | No booking engine (reCAPTCHA enquiry form, deposit links): change detection on sennes.com home + contact page. |
| Rifugio Biella | GitHub, 15 min | `planyo`: Planyo resource search (site 67368, `quantity=2`) plus the calendar's `fetch-data.php` feed to tell full / closed / not yet on sale. Booking window is 365 days ahead. |
| Ücia dles Muntagnoles | page watch, 4 h | Contact form / email only: change detection on the info & reservations page. |

The Booking Südtirol API answers HTTP 403 to GitHub's hosted runners (cloud IP ranges)
while serving the same honest request from an ordinary connection. That is bot
protection, so those four huts are not queried from GitHub (`blocked_on_ci`) and run from
the Mac via launchd (`scripts/install_launchd.sh`), only while it is awake and online.

## Night of 23 June 2027 (check-in Wed 23, check-out Thu 24)

| Hut | Runs on | How |
|---|---|---|
| Rifugio Lagazuoi | GitHub, 15 min | `disponibilita_php`: one `GET disponibilita.php?prm=..&chm=..` (month calendar with per-night, per-room-type bed counts). Sold out and closed look the same. Also works for Rifugio Tissi. |
| Rifugio Scotoni | GitHub, 15 min | `bukly`: `GET scotoni.bukly.com/booking?rooms=2&checkin=..&checkout=..` (JSON embedded in the page); beds counted by the checker. |
| Rifugio Col Gallina | GitHub, 15 min | `bukly`, slug `rifugiocolgallina` |
| Capanna Alpina | page watch, 4 h | No website of its own found (listed as a restaurant; beds unconfirmed): change detection on the Alta Badia tourism listing. |
| Rifugio Averau | GitHub, 15 min | `bukly`, slug `rifugioaverau` |
| Rifugio Scoiattoli | GitHub, 15 min | `scoiattoli_booking`: the site's own step-1 search, `GET rifugioscoiattoli.it/booking/?action=invia&arrivo_insert=..&partenza_insert=..&nadulti=2` (shows availability, books nothing). |
| Rifugio Cinque Torri | page watch, 4 h | Email/phone booking only: change detection on the rooms page + home. |
| Rifugio Nuvolau | GitHub | See below; also checked for 24 Jun. |

## Rifugio Nuvolau: opening watch, nights of 24 and 23 June 2027

Every 5 min from 15 Dec to 15 Feb, every 15 min otherwise, plus a 1-minute probe of the
booking form from 31 Jan 21:00 UTC to 3 Feb 00:00 UTC (`nuvolau-dense.yml`). Engine:
**VikBooking** (WordPress plugin) on rifugionuvolau.it.

| Alert | Source |
|---|---|
| ANNOUNCEMENT (p5 with a date/time, else p4) | Text of the IT/EN homepages and `/dormire/` (they embed the Instagram feed): booking words + 2027/Dec/Jan/Feb; dates and times are extracted. |
| OPENING (p5 "NUVOLAU 2027 BOOKING IS OPEN", 3x 1 min apart, once) | `GET /en/booking-form/`: while bookings are switched off the plugin shows a message; when on, the search form replaces it. A one-off p4 "opening looks imminent" if the calendar shows free beds while the form is still off. One shared lock across all jobs. |
| BEDS (p4, re-alert every 2 h, one GONE) | `GET /en/availability/?view=availability&...&month=<unix ts>`: beds left per dorm per night (5 dorms, 24 beds). |

Last year's opening was staged (from 1 Feb for late June), hence the window to 15 Feb and
the dense probe.

## Night of 28 June 2027: page watch every 4 h

| Hut | How |
|---|---|
| Rifugio Pian de Fontana (preferred) | Text watch of the CAI portal page (id 5942) and piandefontana.it: OPEN (2027 + booking language, negatives ignored, or the portal's booking-calendar markup appearing) and CHANGE alerts. The CAI portal's availability API answers 403 to honest non-browser clients, so it is not queried. |
| Rifugio Sommariva al Pramperet (fallback) | Same, CAI portal id 5925 + rifugiosommarivaalpramperet.it. |

## Split beds

2 free beds in different rooms/units count as available, but the push starts with
`SPLIT across rooms:`.

## Failures

3 consecutive failures of a check give one `FAILING` push (and issue, if issues are on)
and a "Recovered" note later. An unclassifiable engine answer counts as a failure.

## What is public

Public run logs print only `checked <hut>: ok | FAIL (<reason>)`. The public repo receives
one commit per page-watch run: the regenerated STATUS.md (run times + OK/FAILING), which
is the same whether huts are full or available, and also keeps the schedules from being
disabled after 60 days. Results, page text, alert timers and the tracker live in the
private repo `frhl/dolomites-hut-watch-state`. OPENING repeats use ntfy's delayed delivery,
and the Nuvolau checks run the same requests before and after opening, so run durations
don't reveal an alert.
