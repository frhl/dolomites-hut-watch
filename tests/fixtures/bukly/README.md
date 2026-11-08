# Bukly fixtures

Captured 2026-11-08 (around 17:40-18:10 UTC) with curl, using the honest User-Agent from
`hutwatch/http.py` plus `Accept: text/html,application/json;q=0.9,*/*;q=0.5`. No cookies,
Referer or Origin were sent. Every request was a plain GET of the page's own search
(`router.get('/booking', {rooms, checkin, checkout})` in the page JS). Each fixture is the raw
HTML body (HTTP 200, `text/html; charset=utf-8`). The engine state sits in
`<script data-page="app" type="application/json">`.

**Redaction (all files):** the page includes the property's company record with a bcrypt
hash, `"credit_card_password":"$2y$10$..."`. That value was replaced with `"REDACTED"` so a
third party's credential hash does not end up in this repo. No other bytes were changed.

## Real responses

| file | request | what it shows |
|---|---|---|
| `scotoni_2027-06-23_full.html` | `GET https://scotoni.bukly.com/booking?rooms=2&checkin=2027-06-23&checkout=2027-06-24` | target night: `props.allocations == []`, and 2027-06-23 is in `calendarRestrictions.unavailableDates` → FULL |
| `colgallina_2027-06-23_full.html` | `GET https://rifugiocolgallina.bukly.com/booking?rooms=2&checkin=2027-06-23&checkout=2027-06-24` | target night: same → FULL |
| `averau_2027-06-23_full.html` | `GET https://rifugioaverau.bukly.com/booking?rooms=2&checkin=2027-06-23&checkout=2027-06-24` | target night: same → FULL (Averau has `show_unavailable_rooms: 1`, but allocations are still empty) |
| `colgallina_2027-06-18_available.html` | `GET https://rifugiocolgallina.bukly.com/booking?rooms=2&checkin=2027-06-18&checkout=2027-06-19` | AVAILABLE: Room 3 (3 beds free, €130/bed), Room 7 (6, €150), Stanza 10 (3, €160), Room 11 (whole room, sleeps 3, €570) |
| `scotoni_2027-07-20_onebed.html` | `GET https://scotoni.bukly.com/booking?rooms=2&checkin=2027-07-20&checkout=2027-07-21` | the server lists a dorm with `minAvailability: 1` (1 bed) for a 2-adult search → FULL for 2 |
| `colgallina_2027-06-18_to_06-20_split.html` | `GET https://rifugiocolgallina.bukly.com/booking?rooms=2&checkin=2027-06-18&checkout=2027-06-20` | 2-night window: Room 7 and Stanza 10 have 1 bed each (minAvailability is the minimum over both nights). Per-night prices are in `ratePlans[].price[]` |
| `colgallina_2027-12-01_beyond_window.html` | `GET https://rifugiocolgallina.bukly.com/booking?rooms=2&checkin=2027-12-01&checkout=2027-12-02` | after `calendarRestrictions.maxDate` (2027-11-09): the form echoes the dates and allocations are empty → CLOSED (not on sale) |

## EDITED (synthetic) responses: the stay-rule / min-stay path

Bukly's public UI has **no minimum-stay message**. The page, store and search-bar/calendar
chunks (`Index-DK-TcJEk.js`, `Booking-CqFp0r4S.js`, `InfoRequestMobile-hl6cAS2e.js`) contain no
min-stay string, and the calendar data has no min-stay field. A rate that fails a stay rule is just left out.
None was seen live: in all three huts `checkinRestricted == unavailableDates`. So the state
"calendar shows free beds, but the 1-night search lists no rooms" was made by hand. The edit
only replaces the top-level Inertia prop `props.allocations` (the one after `"auth"`) with
`[]`. The calendar is left unchanged, so the night still counts as available:

| file | made from | edits |
|---|---|---|
| `colgallina_2027-06-18_EDITED_minstay_1night.html` | `colgallina_2027-06-18_available.html` | `props.allocations` → `[]` |
| `colgallina_2027-06-18_to_06-20_EDITED_minstay.html` | `colgallina_2027-06-18_to_06-20_split.html` | `props.allocations` → `[]` |
| `colgallina_2027-06-17_to_06-19_EDITED_minstay.html` | `colgallina_2027-06-18_to_06-20_split.html` | `props.allocations` → `[]`. Also changed `bookingEngine.form` checkin/checkout to 2027-06-17/2027-06-19 and the page `url` to `/booking?checkin=2027-06-17&checkout=2027-06-19&rooms=2` |

These files stand for the requests
`GET https://rifugiocolgallina.bukly.com/booking?rooms=2&checkin=2027-06-18&checkout=2027-06-19`,
`...checkin=2027-06-18&checkout=2027-06-20` and `...checkin=2027-06-17&checkout=2027-06-19`.

The edits were made by a script that splices the JSON value at its exact byte range
(`json.JSONDecoder.raw_decode`), so the rest of each file is byte-identical to its source.

Also redacted before publishing: `ref_name` (staff names) and `booking_email_cc` (a personal address) in the embedded hotel/company JSON, replaced with `"REDACTED"`. The engine does not read either field.
