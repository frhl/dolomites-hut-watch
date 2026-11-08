"""Planyo (www.planyo.com) availability checker.

Used by Rifugio Biella / Seekofelhuette (Planyo site/calendar 67368). The hut
sells beds per person: every Planyo "resource" is a room whose `quantity` is its
bed count, and a reservation takes N units (beds) of one room.

Requests (both are what the hut's own public Planyo booking page sends):

1. Search (authoritative, asks for exactly `guests` beds for the one night):
   POST https://www.planyo.com/Plugins/PlanyoFiles/non-planyo-ulap.php
   form: mode=resource_search, site_id, start_date/end_date as dd.mm.YYYY
   (check-in / check-out, is_night=1), quantity=<guests>, plus the widget's
   fixed fields. Response: JSON {"response_code": 0, "response_message": ...,
   "data": {"code": "<html>"}}. The HTML lists one card per room that has
   >= quantity free beds (with a "mode=reserve" link), or a
   <div id='no-search-results'> block. Planyo returns the same refusal for
   "fully booked", "hut closed" and "beyond the booking horizon".

2. Only after a refusal, the availability-calendar feed, to tell those apart:
   GET https://www.planyo.com/fetch-data.php?id=<site>&month=M&year=YYYY&grouped=1
   JSON: res_usage[day]["ad"][resource_id] = beds taken,
         vacations[day][resource_id]["ad"]["v"] = beds blocked (closed).
   Beds per room are not in this feed, so they come from hut.params["rooms"]
   (copied from the `document.resources` JSON in Planyo's embed-calendar.php).

hut.params:
    site_id         Planyo calendar id (int/str), e.g. 67368
    rooms           {resource_id: [name, beds]}; optional, used to count free
                    beds after a refusal (split-room / full detail)
    max_ahead_days  Planyo `rental_max_ahead_days` (default 365): nights beyond
                    today + this are reported CLOSED "booking not yet open"
    language        widget language (default "EN")

Read-only: neither request creates a cart, hold or reservation.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import urllib.parse
from typing import Any

from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.http import USER_AGENT, Fetch, FetchError

ROOT = "https://www.planyo.com/"
ULAP_URL = ROOT + "Plugins/PlanyoFiles/non-planyo-ulap.php"
REST_URL = ROOT + "rest/planyo-reservations.php"
FETCH_DATA_URL = ROOT + "fetch-data.php"

_HREF_RE = re.compile(r"<a\b[^>]*?href=(['\"])(.*?)\1[^>]*>(.*?)</a>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _today() -> dt.date:
    """Separate function so tests can pin 'today' for the booking-horizon rule."""
    return dt.date.today()


def _dmy(d: dt.date) -> str:
    return d.strftime("%d.%m.%Y")


def search_form(site_id: Any, night: dt.date, guests: int, language: str = "EN") -> dict[str, Any]:
    """The resource_search form exactly as the Planyo widget posts it, plus quantity."""
    return {
        "mode": "resource_search",
        "output": "html",
        "site_id": str(site_id),
        "calendar": str(site_id),
        "submitted": ["1", "true"],  # the widget's form really sends both
        "feedback_url": f"{ROOT}booking.php?calendar={site_id}",
        "start_date": _dmy(night),
        "end_date": _dmy(night + dt.timedelta(days=1)),
        "sort_fields": "name,price",
        "sort": "name",
        "is_night": "1",
        "granulation": "1440",
        "custom-language": language,
        "quantity": str(guests),
        "ulap_url": REST_URL,
        "language": language,
        "plugin_mode": "10",
        "dynm": "1",
        "user_agent": USER_AGENT,
    }


def _search_html(resp) -> tuple[int, str, str]:
    obj = resp.json()
    if not isinstance(obj, dict) or "response_code" not in obj:
        raise FetchError(f"unexpected Planyo search response from {resp.url}")
    try:
        code = int(obj["response_code"])
    except (TypeError, ValueError) as e:
        raise FetchError(f"bad Planyo response_code {obj.get('response_code')!r}") from e
    data = obj.get("data")
    body = data.get("code") if isinstance(data, dict) else None
    return code, str(obj.get("response_message") or ""), body if isinstance(body, str) else ""


def bookable_rooms(code_html: str, start: str, end: str) -> dict[str, str]:
    """{resource_id: room name} for rooms with a 'Make reservation' link for start..end."""
    names: dict[str, str] = {}
    bookable: list[str] = []
    for _, href, inner in _HREF_RE.findall(code_html):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(href)).query)
        rid = (q.get("resource_id") or [""])[0]
        if not rid:
            continue
        mode = (q.get("mode") or [""])[0]
        text = html.unescape(_TAG_RE.sub("", inner)).strip()
        if mode == "resource_desc" and text and text.lower() != "details":
            names.setdefault(rid, text)
        elif mode == "reserve":
            # ignore links for other dates (defensive: response must match the query)
            if (q.get("start_date") or [start])[0] == start and (q.get("end_date") or [end])[0] == end:
                if rid not in bookable:
                    bookable.append(rid)
    return {rid: names.get(rid, f"room {rid}") for rid in bookable}


def _per_resource(day_entry: Any, *, vacation: bool) -> dict[str, int]:
    """Sum units per resource for one day of res_usage (kind->rid->n) or vacations (rid->kind->{v})."""
    out: dict[str, int] = {}
    if not isinstance(day_entry, dict):
        return out
    if vacation:
        for rid, kinds in day_entry.items():
            if isinstance(kinds, dict):
                for x in kinds.values():
                    if isinstance(x, dict):
                        out[str(rid)] = out.get(str(rid), 0) + int(x.get("v", 0) or 0)
    else:
        for per in day_entry.values():
            if isinstance(per, dict):
                for rid, n in per.items():
                    out[str(rid)] = out.get(str(rid), 0) + int(n or 0)
    return out


def _calendar_day(fetch: Fetch, site_id: Any, night: dt.date) -> tuple[dict[str, int], dict[str, int]]:
    resp = fetch("GET", FETCH_DATA_URL,
                 params={"id": str(site_id), "month": str(night.month), "year": str(night.year), "grouped": "1"})
    obj = resp.json()
    if not isinstance(obj, dict) or str(obj.get("month")) != str(night.month) or str(obj.get("year")) != str(night.year):
        raise FetchError(f"Planyo calendar feed did not return {night.year}-{night.month:02d}")
    day = str(night.day)
    usage_all, vac_all = obj.get("res_usage"), obj.get("vacations")
    usage = _per_resource(usage_all.get(day) if isinstance(usage_all, dict) else None, vacation=False)
    vac = _per_resource(vac_all.get(day) if isinstance(vac_all, dict) else None, vacation=True)
    return usage, vac


def _short(name: str) -> str:
    return re.sub(r"\s*-\s*\d+\s*persone?\s*$", "", name, flags=re.I).strip() or name


def check(hut: Hut, night: dt.date, guests: int, fetch: Fetch) -> CheckResult:
    p = hut.params
    site_id = p["site_id"]
    lang = p.get("language", "EN")
    when = _dmy(night)

    # 1. Planyo's own search for `guests` beds, night -> night+1
    form = search_form(site_id, night, guests, lang)
    code, msg, code_html = _search_html(fetch("POST", ULAP_URL, data=form))
    if code != 0:
        return CheckResult(Status.UNKNOWN, f"Planyo search error for {when}: {msg or code}")
    rooms_found = bookable_rooms(code_html, form["start_date"], form["end_date"])
    if rooms_found:
        names = [_short(n) for n in rooms_found.values()]
        return CheckResult(
            Status.AVAILABLE,
            f"room(s) with {guests} free beds on {when}: {', '.join(names)}",
            options=[f"{n} (resource {rid})" for rid, n in rooms_found.items()],
        )
    if "no-search-results" not in code_html:
        return CheckResult(Status.UNKNOWN, f"unrecognised Planyo search result for {when}")

    # 2. Refused: full, closed or not yet on sale? Ask the calendar feed.
    usage, vac = _calendar_day(fetch, site_id, night)
    rooms_cfg: dict[str, Any] = {str(k): v for k, v in (p.get("rooms") or {}).items()}

    horizon = _today() + dt.timedelta(days=int(p.get("max_ahead_days", 365)))
    if night > horizon:
        opens = night - dt.timedelta(days=int(p.get("max_ahead_days", 365)))
        return CheckResult(Status.CLOSED,
                           f"booking not yet open for {when} (Planyo sells {p.get('max_ahead_days', 365)} "
                           f"days ahead; expected to open ~{_dmy(opens)})")

    if rooms_cfg:
        all_closed = all(vac.get(rid, 0) >= int(v[1]) for rid, v in rooms_cfg.items())
    else:
        all_closed = bool(vac) and not usage
    if all_closed:
        return CheckResult(Status.CLOSED, f"hut not bookable on {when}: calendar marks every room closed")

    if not rooms_cfg:
        return CheckResult(Status.FULL, f"no room with {guests} free beds on {when} "
                                        f"({sum(usage.values())} beds booked)")

    free = {rid: max(0, int(v[1]) - usage.get(rid, 0) - vac.get(rid, 0)) for rid, v in rooms_cfg.items()}
    lines = [f"{_short(str(rooms_cfg[rid][0]))}: {n} free" for rid, n in free.items() if n > 0]
    extra = sorted((set(usage) | set(vac)) - set(rooms_cfg))
    note = f"; unknown room ids {', '.join(extra)} (update params.rooms)" if extra else ""
    total, best = sum(free.values()), max(free.values(), default=0)

    if best >= guests:
        # Search and calendar disagree: don't guess (maybe a min-stay/other rule).
        return CheckResult(Status.UNKNOWN,
                           f"Planyo search found no room for {guests} on {when}, but the calendar shows "
                           f"{', '.join(lines)} - possible min-stay or other rule; check the booking page{note}",
                           options=lines)
    if total >= guests:
        return CheckResult(Status.AVAILABLE,
                           f"{total} single beds free on {when} but in different rooms "
                           f"({', '.join(lines)}): needs separate bookings{note}",
                           options=lines, split=True)
    if total:
        return CheckResult(Status.FULL, f"full for {guests} on {when}: only {total} bed(s) free "
                                        f"({', '.join(lines)}){note}", options=lines)
    return CheckResult(Status.FULL, f"fully booked on {when} (0 of {sum(int(v[1]) for v in rooms_cfg.values())} "
                                    f"beds free){note}")
