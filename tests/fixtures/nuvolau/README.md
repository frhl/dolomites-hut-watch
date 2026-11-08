# nuvolau fixtures (VikBooking 1.8.15 on rifugionuvolau.it)

Recorded 2026-11-08 (UTC times below) with `curl`, method GET, no cookies sent, no
Referer/Origin, header `User-Agent: <hutwatch.http.USER_AGENT>` (curl default
`Accept: */*`). All returned HTTP 200 `text/html; charset=UTF-8`. Nothing was posted,
held or booked. Bodies are stored byte-for-byte unless marked EDITED.

| File | Exact request | Recorded | Real / edited | Used for |
|---|---|---|---|---|
| `booking-form_en_disabled.html` | `GET https://rifugionuvolau.it/en/booking-form/` | 17:50:56 | real, unedited | **NOT OPEN.** VikBooking search view with bookings switched off: `<div class="wrap plugin-container">` holds only `Rooms closed, see you in June 2027!` |
| `availability_2027-06.html` | `GET https://rifugionuvolau.it/en/availability/?view=availability&room_ids%5B0%5D=4&room_ids%5B1%5D=6&room_ids%5B2%5D=8&room_ids%5B3%5D=5&room_ids%5B4%5D=7&showtype=2&month=1811808000` | 17:52:32 | real, unedited | June 2027 as of today: all 30 nights of all 5 bed types `vbo-occupied-cell`, `data-units-left="0"` (24/24 units booked = closure). Not-open and open-but-full scenarios |
| `availability_2026-09.html` | same as above with `month=1788220800` | 17:52:50 | real, unedited | Nuvolau's own in-season month (Sep 2026, past): real `vbo-occupied-cell vbo-partially-cell` cells. 15 Sep 5 free (8-bed room), 2 Sep 1+1 in two dorms, 3 Sep 1 free, 20 Sep 2 free (last night), 21 Sep+ blocked |
| `knaben_search-view_enabled.html` | `GET https://booking.knaben.no/nb/sok-leilighet/` | 17:57:48 | real, unedited (sibling site) | **OPEN form shape.** Another VikBooking (1.8.20) WordPress site with bookings on: the same `plugin-container` holds `<div class="vbdivsearch vbo-search-mainview"><form ... method="post">` with hidden `task=search`. Nuvolau's enabled form can't be observed until bookings open |
| `availability_2027-06_edited_beds.html` | derived from `availability_2027-06.html` | — | **EDITED** (2 cells) | **OPEN WITH BEDS.** See below |

Edits in `availability_2027-06_edited_beds.html` (everything else byte-identical, incl. CRLFs):

- room 4 (3-bed), `23/06/2027`: `class="vbo-occupied-cell"` booked 3 / left 0 ->
  `class="vbo-occupied-cell vbo-partially-cell"` booked 2 / left 1 (markup copied from the
  real 02/09/2026 room-4 cell). 23 Jun -> 1 bed -> FULL for 2 guests.
- room 7 (8-bed), `24/06/2027`: booked 8 / left 0 -> `vbo-occupied-cell vbo-partially-cell`
  booked 6 / left 2 (markup copied from the real 20/09/2026 room-7 cell). 24 Jun -> AVAILABLE.

The availability request is the page's own month form (`<form ... method="post"
name="vbmonths">` posting `month`, `room_ids[]`, `showtype=2` to that same URL) sent as a GET.
The template reads these from `request`, so GET is honoured (June 2027 shown as selected).
`month` is the `<option>` value: unix ts of day 1 00:00 UTC (1811808000 = 2027-06-01).

Not observed live and covered by in-memory edits in the tests (no files stored):

- **Fully free night** (`<td class="vbo-free-cell" ...></td>`, no `data-units-*` span): the
  shape comes from the plugin template `site/views/availability/tmpl/default.php` (tag 1.8.15,
  read as text from cdn.jsdelivr.net). Not seen in any Nuvolau month fetched.
- **Unknown cell class -> UNKNOWN**, error bodies (HTTP 500, challenge-like page, page with
  no tables), wrong month returned.
- **Nuvolau's own enabled search form**: will be first seen on 2027 opening day.

Also redacted before publishing: contact e-mail addresses and phone links in the knaben.no page (replaced with placeholders); the engine does not read them.
