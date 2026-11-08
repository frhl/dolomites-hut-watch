# Status: what each hut is checked with

Last inspected 2026-11-08. Every checker uses the honest User-Agent in `hutwatch/http.py`,
read-only requests only (no carts, holds, enquiry forms, personal data or payments), and
nothing that gets around bot protection. "Now" = the result for 2 guests on 2026-11-08.

**Timing caveat:** GitHub can delay scheduled runs by 10 to 30 minutes at busy times (and
skip some). The 5- and 15-minute schedules are best effort. For Nuvolau this means the
**ANNOUNCEMENT** alert (the published opening date/time) is the one that matters for being
online on the day; the OPENING alert may arrive after the beds are gone.

## Night of 22 June 2027 (check-in Tue 22, check-out Wed 23) — every 15 min (Biella) / hourly from the Mac

> **Run from the Mac, not GitHub:** the Booking Südtirol API (Fanes, Lavarella, Pederü,
> Fodara Vedla) returns **HTTP 403 to GitHub's hosted runners** (cloud IP ranges), while the
> same honest request works from an ordinary connection (verified 2026-11-08: all four
> answered FULL). They are skipped on GitHub (`blocked_on_ci`) and checked **at most hourly
> from your Mac** by launchd (`scripts/install_launchd.sh`), same request, ntfy alerts only.
> Only while the Mac is awake and online. Biella below runs on GitHub as normal.

| Hut | How | Now | Notes |
|---|---|---|---|
| Rifugio Fanes | Mac, hourly: `fanes_family`: Booking Südtirol widget API, `GET api.widgets.bookingsuedtirol.com/v6/properties/13308/availabilities` (per-arrival-night rules), queried as one room for 2 *and* as two 1-person units (dorm beds) | FULL | Min stay varies by date (23 Jun needs 2 nights). Limitation: a single free night between bookings under a 2-night minimum is invisible to the API, so phoning can still find beds. |
| Rifugio Lavarella | Mac, hourly: `fanes_family`, property 13004 | FULL | June is on sale online; nothing bookable 17–30 Jun (sold out or held back; the API can't tell). |
| Berggasthaus Pederü | Mac, hourly: `fanes_family`, property 10716 | FULL | Nothing bookable after 19 Jun. |
| Rifugio Fodara Vedla | Mac, hourly: `fanes_family`, property 12869 | FULL | 23 Jun had a free 6-person dorm unit on 8 Nov. |
| Rifugio Sennes | **page-change** (4 h page watch): sennes.com home + contact page | — | No booking engine: reCAPTCHA enquiry form + Stripe deposit links only. Phone +39 0474 646355. |
| Rifugio Biella | `planyo`: `POST planyo.com/.../non-planyo-ulap.php` resource search (site 67368, `quantity=2`), plus the calendar's `fetch-data.php` feed to tell full / closed / not yet on sale | FULL (0 of 47 beds) | Not on the CAI portal. 2 beds in different rooms count as available (detail says so). Booking window is 365 days ahead. |
| Ücia dles Muntagnoles | **page-change** (4 h): info & reservations page | — | Contact form / email only. Phone +39 347 5214753. |

## Night of 23 June 2027 (check-in Wed 23, check-out Thu 24) — every 15 min

| Hut | How | Now | Notes |
|---|---|---|---|
| Rifugio Lagazuoi | `disponibilita_php`: one `GET disponibilita.php?prm=..&chm=..` (month calendar, per-night per-room-type bed counts) | FULL | Grey = sold out *or* closed. Only 7–10 Jun green in June. Same engine works for Rifugio Tissi. |
| Rifugio Scotoni | `bukly`: `GET scotoni.bukly.com/booking?rooms=2&checkin=..&checkout=..` (JSON embedded in the page) | FULL | Engine counts beds itself (the calendar says "≥1 free bed" only). |
| Rifugio Col Gallina | `bukly`, slug `rifugiocolgallina` | FULL | |
| Capanna Alpina | **page-change** (4 h): Alta Badia tourism listing | — | No website of its own found; listed as a restaurant/bar, beds unconfirmed. Phone +39 0471 849418. Ring them. |
| Rifugio Averau | `bukly`, slug `rifugioaverau` | FULL | |
| Rifugio Scoiattoli | `scoiattoli_booking`: the site's own search, `GET rifugioscoiattoli.it/booking/?action=invia&arrivo_insert=..&partenza_insert=..&nadulti=2` (step 1 only: shows availability, books nothing) | FULL | Only dorm beds have appeared online so far; the room-parsing path is untested on a live response. Waiting list never used. |
| Rifugio Cinque Torri | **page-change** (4 h): rooms page + home | — | Email/phone booking only. Site: "L'estate 2027 è quasi al completo! … risponderemo solo in caso di disponibilità". Phone +39 0436 2902. |
| Rifugio Nuvolau | see below | | Also checked for 24 Jun. |

## Rifugio Nuvolau — opening watch, nights of 24 and 23 June 2027

Every 5 min from 15 Dec to 15 Feb, every 15 min otherwise, plus a **1-minute probe of the
booking form from 31 Jan 21:00 UTC to 3 Feb 00:00 UTC** (`nuvolau-dense.yml`: one ~3 h job
per 3-h cron slot, 1 request per minute; jobs can start 10–30 min late). The 5/15-min ticks
and the dense job share one OPENING lock (`state/nuvolau_opening.json` + the open OPENING
issue), so the urgent alert is sent once. All subject to the GitHub delays above.

Engine: **VikBooking** (WordPress plugin) on rifugionuvolau.it, engine `nuvolau`. ~5 requests per run.

| Alert | Source | Now |
|---|---|---|
| ANNOUNCEMENT (push p5 if a date/time is given, else p4) | Text of https://rifugionuvolau.it/, https://rifugionuvolau.it/en/, https://rifugionuvolau.it/dormire/ (homepages embed the Instagram feed, where last year's opening dates were posted). Booking words + 2027/Dec/Jan/Feb; dates and times are pulled out of the sentence. | Baseline: "Prenotazioni 2027: a partire da gennaio 2027 sul sito web" (no exact date yet). |
| OPENING (push p5 "NUVOLAU 2027 BOOKING IS OPEN", 3x, 1 min apart, once) | `GET /en/booking-form/`: while bookings are switched off the plugin shows only a message; when on, the search form replaces it. Fires even if every night is taken. If the form is live but the calendar request fails (overload), it still fires. If the calendar shows free beds while the form is still off, a one-off p4 "opening looks imminent" push is sent. | Off: "Rooms closed, see you in June 2027!" |
| BEDS (p4, re-alert every 2 h, one GONE) | `GET /en/availability/?view=availability&room_ids[]=4,6,8,5,7&showtype=2&month=<unix ts of 1st>`: beds left per dorm per night (5 dorms, 24 beds). Engine counts beds itself (≥2, may be split across dorms; the detail lists them). | CLOSED (bookings off; June 2027 fully blocked). |

Notes:
- **Last year's opening was staged**: 1 Feb 2026 for 20–30 June, then July/Aug/Sep every 2 days,
  "per evitare il sovraccarico". The site now says 2027 bookings start "from January 2027".
  If 2027 is staged the same way, our June nights could open on or around 1 Feb, hence the
  window to 15 Feb and the dense probe.
- On opening day the site may be overloaded; failures count toward the 3-failure FAILING alert.
- Phone +39 0436 867938 (active only in the season), info@rifugionuvolau.it.

## Night of 28 June 2027 — page watch every 4 h

| Hut | How | Notes |
|---|---|---|
| Rifugio Pian de Fontana (preferred) | **text watch**: CAI portal page id 5942 + piandefontana.it (OPEN + CHANGE alerts) | The CAI portal's availability API (`booking.prenotarifugi.cai.it/backend/web/api/...`) answers 403 to honest non-browser clients, so it is not queried. The page watch also alerts if the portal's booking-calendar markup appears. Site still shows the 2026 season. |
| Rifugio Sommariva al Pramperet (fallback) | same, CAI portal id 5925 + rifugiosommarivaalpramperet.it | Site homepage has no season text yet; any booking-relevant text appearing triggers CHANGE. |

## Split beds

2 free beds in different rooms/units count as **available**, but the push starts with
`SPLIT across rooms:` and the issue says the beds are in different rooms (engines set
`CheckResult.split`: Lagazuoi/Tissi, Bukly, Planyo, Scoiattoli, Nuvolau by beds per
room/dorm; Booking Südtirol when only the "two 1-person units" layout is bookable).

## Failure handling

3 consecutive failures for any hut, page or Nuvolau check give one `FAILING:` issue (plus
an ntfy push for the fast checks) and a "Recovered" comment when it works again. An engine
answer that can't be classified (UNKNOWN) counts as a failure, so a changed booking page
can't fail silently.
