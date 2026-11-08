# disponibilita_php fixtures

Raw, unedited response bodies, recorded 2026-11-08 (UTC times below) with `curl`,
method GET, no cookies, no Referer/Origin, header
`User-Agent: <hutwatch.http.USER_AGENT>` (curl default `Accept: */*`). All returned
HTTP 200 `text/html; charset=UTF-8`.

| File | Exact request | Recorded | Used for |
|---|---|---|---|
| `lagazuoi_2027-06.html` | `GET https://rifugiolagazuoi.com/EN/disponibilita.php?prm=17&chm=1` | 17:42:50 | June 2027. **Target night 23 Jun = grey (`chiuso`) -> FULL.** 7, 8, 9 Jun green -> AVAILABLE (9 Jun includes a room line); 10 Jun green with 1 dorm bed -> FULL for 2 guests |
| `tissi_2027-06.html` | `GET https://www.rifugiotissi.com/EN/disponibilita.php?prm=17&chm=1` | 17:42:56 | June 2027 at Tissi. 26 Jun green, 33 places -> AVAILABLE; 9 Jun private room without "n. K" count; 30 Jun 1 bed -> FULL for 2 |
| `lagazuoi_2026-11.html` | `GET https://rifugiolagazuoi.com/EN/disponibilita.php` (no query = current month) | 17:40:18 | November 2026, every day grey (closed season); shows grey cannot be told apart from sold out |

`?prm=17&chm=1` is the exact request the engine sends for a June 2027 night when
run in 2026 (month index 18 from January 2026, sent the way the page's own
"next month" arrow does). `?prm=11&chm=7` returned a byte-identical table.

States that could not be observed live:

- **Min-stay refusal:** this engine has none. The calendar is a per-night table
  without a guest count or stay length, so no min-stay fixture exists.
- **CLOSED vs FULL:** the site uses one grey class (`chiuso`) for both, so the engine
  reports FULL.
- **Unrecognised day class -> UNKNOWN:** `test_unknown_day_state` edits
  `lagazuoi_2027-06.html` in memory (day 23 `class="chiuso"` -> `class="riservato"`).
  No edited file is stored.
- **Error bodies (HTTP 500, page without the table):** built inline in the tests.
