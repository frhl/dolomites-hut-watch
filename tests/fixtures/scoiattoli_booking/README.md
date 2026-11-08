# scoiattoli_booking fixtures

Raw, unedited response bodies from Rifugio Scoiattoli's own booking page, recorded
2026-11-08 (UTC times below) with `curl`, method GET, no cookies, no Referer/Origin,
header `User-Agent: <hutwatch.http.USER_AGENT>` (curl default `Accept: */*`). All
returned HTTP 200 `text/html; charset=UTF-8`. Every request is the page's first step
(list free beds). Nothing was selected, held or booked, and no personal data was sent.

Base URL: `https://www.rifugioscoiattoli.it/booking/`

Two request shapes were used:

- **engine**: `?action=invia&arrivo_insert=<YYYY-MM-DD>&partenza_insert=<YYYY-MM-DD>&nadulti=2&nbambini_3_12=0&nbambini_0_2=0`.
  This is what `scoiattoli_booking.check` sends. It is also the shape of the site's own
  "Seleziona" links to alternative dates.
- **form**: what the page's form submits (Italian page):
  `?action=invia&arrivo=<d Mese, yyyy>&arrivo_insert=<YYYY-MM-DD>&partenza=<d Mese, yyyy>&partenza_insert=<YYYY-MM-DD>&nadulti=2&nbambini_3_12=0`.
  For 23 Jun and 28 Sep 2027 both shapes gave byte-identical bodies, so the server
  reads only the `*_insert` fields.

| File | Shape | Exact request (after base URL) | Recorded | Result |
|---|---|---|---|---|
| `target_2027-06-23_full.html` | engine | `?action=invia&arrivo_insert=2027-06-23&partenza_insert=2027-06-24&nadulti=2&nbambini_3_12=0&nbambini_0_2=0` | 17:55:52 | **Target night: "Non ci sono posti disponibili", no alternative dates offered, waiting list offered -> FULL** |
| `full_alternatives_2026-12-31.html` | form | `?action=invia&arrivo=31+Dicembre%2C+2026&arrivo_insert=2026-12-31&partenza=1+Gennaio%2C+2027&partenza_insert=2027-01-01&nadulti=2&nbambini_3_12=0` | 17:54:54 | FULL, plus 5 other 1-night arrivals suggested (28, 29, 30 Dec, 2, 3 Jan) |
| `available_2027-01-12.html` | form | `?action=invia&arrivo=12+Gennaio%2C+2027&arrivo_insert=2027-01-12&partenza=13+Gennaio%2C+2027&partenza_insert=2027-01-13&nadulti=2&nbambini_3_12=0` | 17:54:16 | AVAILABLE: step-2 form, "Camerata 9" select 0..8 -> 8 dorm beds |
| `available_2027-09-28.html` | engine | `?action=invia&arrivo_insert=2027-09-28&partenza_insert=2027-09-29&nadulti=2&nbambini_3_12=0&nbambini_0_2=0` | 17:56:38 | AVAILABLE: "Camerata 9" 3 beds + "Camerata 1" 1 bed = 4 places (identical to the form-shape request at 17:54:33) |
| `closed_2027-05-05.html` | engine | `?action=invia&arrivo_insert=2027-05-05&partenza_insert=2027-05-06&nadulti=2&nbambini_3_12=0&nbambini_0_2=0` | 17:55:42 | "Hai selezionato delle date non corrette!" (outside the date picker's seasons) -> CLOSED |

States that could not be observed live (edited in memory in the tests, no edited file is stored):

- **Min-stay refusal:** none exists as far as observed. A 1-night New Year's Eve query
  got a plain "no places" with other 1-night dates, not a min-stay message, so there is
  no min-stay fixture. An unknown message (test: "Soggiorno minimo 2 notti") -> UNKNOWN.
- **Fewer free places than guests:** `available_2027-09-28.html` with the echo
  `N. Adulti: 2` changed to `5`, queried for 5 guests -> FULL ("only 4 place(s)").
- **Private room offered:** no response contained one. The test inserts a `<label>` with
  `<input class='chk_id_camera' data-letti='2'>` (markup inferred from the page's own
  JS, which reads `data-letti` from checked `.chk_id_camera` inputs) and empties the dorm
  select of `available_2027-01-12.html`. This markup is an assumption.
- **Error bodies (HTTP 500, page without the Arrivo/Partenza echo):** built inline.
