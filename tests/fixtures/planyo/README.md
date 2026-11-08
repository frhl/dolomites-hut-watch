# Planyo fixtures (Rifugio Biella / Seekofelhuette, Planyo site 67368)

All captured live on 2026-11-08 between 17:46 and 17:50 GMT. They were sent with the
honest `hutwatch.http.USER_AGENT`, default `Accept`/`Accept-Language` from
`hutwatch/http.py`, no cookies, no Referer/Origin and no API key. Bodies are
byte-for-byte what the server returned, except the one file marked EDITED.

## Requests

### Search (`search_*.json`)

    POST https://www.planyo.com/Plugins/PlanyoFiles/non-planyo-ulap.php
    Content-Type: application/x-www-form-urlencoded
    -> 200, Content-Type: text/plain; charset=UTF-8, JSON body

Exact form body as sent. `<S>`/`<E>` are the check-in/check-out dates per file
(below), and `<UA>` is the URL-encoded USER_AGENT:

    mode=resource_search&output=html&site_id=67368&calendar=67368&submitted=1
    &feedback_url=https%3A%2F%2Fwww.planyo.com%2Fbooking.php%3Fcalendar%3D67368
    &start_date=<S>&end_date=<E>&sort_fields=name%2Cprice&sort=name&is_night=1
    &granulation=1440&custom-language=EN&submitted=true&quantity=2
    &ulap_url=https%3A%2F%2Fwww.planyo.com%2Frest%2Fplanyo-reservations.php
    &language=EN&plugin_mode=10&dynm=1&user_agent=<UA>

(The line breaks are only for readability; the body is one line.) The engine sends
the same fields, but its `urlencode` puts the two `submitted` values next to each other.

| file | S | E | what it shows |
|---|---|---|---|
| `search_target_20270622_q2.json` | 22.06.2027 | 23.06.2027 | **target night now**: `no-search-results`. The calendar has 0 of 47 beds free, so FULL |
| `search_available_20270623_q2.json` | 23.06.2027 | 24.06.2027 | AVAILABLE: one card, "Pelmo - 6 persone" (resource 224732, 2 free beds) |
| `search_closed_20270605_q2.json` | 05.06.2027 | 06.06.2027 | `no-search-results`. The calendar marks every room as vacation (hut opens 12 June), so CLOSED |
| `search_notopen_20280622_q2.json` | 22.06.2028 | 23.06.2028 | `no-search-results`. The date is beyond `rental_max_ahead_days` = 365, so CLOSED "booking not yet open" |
| `search_split_20270630_q2.json` | 30.06.2027 | 01.07.2027 | `no-search-results`. The calendar has 1 bed free in Croda del Becco and 1 in Sorapis, so 2 beds are split across rooms |
| `search_minstay_20270623_q2_EDITED.json` | (23.06.2027) | (24.06.2027) | **EDITED, not observed live**, see below |

### Calendar feed (`fetchdata_*.json`)

    GET https://www.planyo.com/fetch-data.php?id=67368&month=6&year=2027&grouped=1   -> fetchdata_2027_06.json
    GET https://www.planyo.com/fetch-data.php?id=67368&month=6&year=2028&grouped=1   -> fetchdata_2028_06.json
    -> 200, Content-Type: application/json; charset=utf-8

- `res_usage[day]["ad"][resource_id]` is the number of beds taken.
- `vacations[day][resource_id]["ad"]["v"]` is the number of beds blocked.
- In June 2027, days 1-11 are vacation for every room.
- In June 2028, all 30 days are vacation for every room, which is how the feed looks
  beyond the booking horizon.

The page's own calendar (planyo.js `js_fetch_calendar_data`) also adds
`&month2=7&year2=2027` to prefetch the next month. An earlier capture with that extra
month (not saved here) had identical June `res_usage`.

## Room capacities (`hut.params["rooms"]`)

The calendar feed does not include beds per room. They come from the
`document.resources` JSON in

    GET https://www.planyo.com/embed-calendar.php?calendar=67368&feedback_url=https%3A%2F%2Fwww.planyo.com%2Fbooking.php%3Fcalendar%3D67368&modver=2.7&background=none&custom-language=EN&ifr=calp_645184578&usage=resform&set_date=2027/06/22&

which gives these `quantity` values: 224735 Cima Nove 6, 224733 Col de Lasta 4,
224780 Croda del Becco 2, 224728 Croda Rossa 6, 224732 Pelmo 6, 224734 Piccola Croda 7,
224779 Sorapis 8, 224729 Tofane 8. That is 47 beds. Every room has `min_rental_time`
24 h (so 1 night is allowed) and `rental_max_ahead_days` 365. The vacation values
(`v`) in the feed equal these capacities.

## Edited fixture

The engine has no minimum-stay rule: every room allows 24 h. So a min-stay
refusal could not be observed. `search_minstay_20270623_q2_EDITED.json` is
`search_target_20270622_q2.json` with one change: `set_date=2027\/06\/22` became
`set_date=2027\/06\/23` in the iframe URL. That is a real "no results" body
presented as the answer for 23 June.

Paired with the real `fetchdata_2027_06.json`, where 23 June has Pelmo with 2 free
beds, it simulates "the search refuses although the calendar shows a room with
enough beds", which is what a min-stay or other rule would look like. The engine
returns UNKNOWN for this disagreement instead of guessing.

## Cross-checks done live (not saved)

- The same search for 23.06.2027 *without* `quantity` listed Croda Rossa (1 free) and
  Pelmo (2 free), which are exactly the rooms the calendar shows with at least 1 bed
  free. With `quantity=2` only Pelmo came back, so the server applies the bed count
  per room.
- The search for 22.06.2027 without `quantity` was also `no-search-results`.
