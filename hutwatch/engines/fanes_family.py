"""Booking Südtirol (HGV) widget engine.

Used by Rifugio Fanes, Berggasthaus Pederü and Schutzhaus Fodara Vedla (Booking Südtirol v2
widget, https://widget.bookingsuedtirol.com/v2/bundle.js) and Rifugio Lavarella (older
widget.js; same v6 API for property 13004). Rifugio Sennes does NOT use it (enquiry form only).

Primary request: the widget calendar's own per-day lookup, a public read-only GET

    GET https://api.widgets.bookingsuedtirol.com/v6/properties/{property_id}/availabilities
        ?from=YYYY-MM-DD&to=YYYY-MM-DD&guests=[[18,18]]&sourceId=98
    -> [{"date": "<arrival>", "departures": [{"departure": "<date>", "rule": "<rule>"}, ...]}, ...]

`from`/`to` bound the ARRIVAL dates only; departures may run past `to`. An arrival date is
listed only if at least one stay starting that day can be booked. Rules:
  departure_possible          stay arrival->departure bookable online
  minimum_stay_not_fulfilled  nights free but the stay is too short (e.g. 1-night refused)
  maximum_stay_not_fulfilled  nights free but the stay is too long
So night N is free for the guests iff N is inside some listed stay [arrival, departure).
A window with no bookable arrival at all (every layout) is reported CLOSED: the API returns
the same [] for a closed hut, a period not yet released online, and a sold-out month.

`guests` is a JSON list of rooms, each a list of ages (adults = 18). One room for 2
([[18,18]]) never matches per-bed dormitory units (e.g. Fanes "dormitory" has occupancy
max 1); two 1-person units ([[18],[18]]) do. Both layouts are queried.

The offers endpoint (`.../offers`, what the widget shows after picking dates) returns the
same empty body for "1-night stay refused" and "full", so it is only used, best-effort,
to name room types and prices once a night is already known to be available.

hut.params:
  property_id   int, required (Fanes 13308, Pederü 10716, Fodara Vedla 12869, Lavarella 13004)
  source_id     int, widget `easy_channel_id`, default 98
  max_adults    int, widget per-room max adults (one-room layout skipped above it), default 4
  max_children  int, echoed in the offers request like the widget does, default 3
  lang          default "en"
  lookback_days how far before `night` to look for stays covering it, default 14
  details       fetch offers + room names when available, default True
  api           API base, default https://api.widgets.bookingsuedtirol.com/v6
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
from typing import Any

from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.http import Fetch, FetchError

API = "https://api.widgets.bookingsuedtirol.com/v6"
HEADERS = {"Accept": "application/json"}  # what the widget's fetch() sends
ADULT_AGE = 18
SOURCE_ID = 98

OK = "departure_possible"
MIN = "minimum_stay_not_fulfilled"
MAX = "maximum_stay_not_fulfilled"
RULE_TEXT = {MIN: "minimum stay", MAX: "maximum stay"}

Stay = tuple[dt.date, dt.date, str]  # (arrival, departure, rule)


def check(hut: Hut, night: dt.date, guests: int, fetch: Fetch) -> CheckResult:
    p = hut.params
    pid = int(p["property_id"])
    sid = int(p.get("source_id", SOURCE_ID))
    base = str(p.get("api", API)).rstrip("/")
    max_adults = int(p.get("max_adults", 4))
    lookback = int(p.get("lookback_days", 14))
    frm, to = _window(night, lookback)

    per_layout: list[tuple[str, list[list[int]], list[Stay], list[Stay]]] = []
    for label, rooms in _layouts(guests, max_adults):
        resp = fetch(
            "GET",
            f"{base}/properties/{pid}/availabilities",
            params={"from": frm.isoformat(), "to": to.isoformat(),
                    "guests": _guests_json(rooms), "sourceId": sid},
            headers=HEADERS,
        )
        stays = _parse_availabilities(resp.json(), resp.url)
        covering = [s for s in stays if s[0] <= night < s[1]]
        per_layout.append((label, rooms, covering, stays))

    options = [_layout_line(label, cov, night) for label, _, cov, _ in per_layout]

    bookable = [(label, rooms, s) for label, rooms, cov, _ in per_layout
                for s in cov if s[2] == OK]
    if bookable:
        label, rooms, stay = min(bookable, key=lambda b: _stay_rank(b[2], night))
        detail = f"{_d(night)} bookable for {guests}: {label}, {_span(stay)}"
        one_night = _one_night_rule(per_layout, night)
        if one_night and one_night != OK:
            detail += f" (1-night stay refused: {RULE_TEXT.get(one_night, one_night)})"
        if p.get("details", True):
            extra = _room_summary(fetch, base, pid, sid, p, rooms, stay)
            if extra:
                detail += f" - {extra}"
        # Two 1-person units (dorm beds or singles) may not be in the same room; only call it
        # split when no single-room-for-2 stay covers the night.
        together = any(len(r) == 1 for _, r, _ in bookable)
        return CheckResult(Status.AVAILABLE, detail, options, split=not together)

    blocked = [s for _, _, cov, _ in per_layout for s in cov]
    if blocked:
        # Night is free, but every online stay covering it is refused by a stay rule.
        rules = sorted({s[2] for s in blocked})
        if MIN in rules and all(r in RULE_TEXT for r in rules):
            why = "/".join(RULE_TEXT[r] for r in rules)
            return CheckResult(
                Status.MIN_STAY,
                f"{_d(night)} free for {guests} but every online stay covering it is refused "
                f"({why} rule) - call the hut",
                options,
            )
        return CheckResult(Status.UNKNOWN, f"rule(s) {rules} block every stay covering "
                           f"{_d(night)}", options)

    all_stays = [s for *_, stays in per_layout for s in stays]
    if not all_stays:
        # Whole window empty in every layout: treated as not (yet) sellable online. The API
        # gives the same [] for a closed hut, an unreleased period and a sold-out month.
        return CheckResult(
            Status.CLOSED,
            f"nothing on sale online for {guests} anywhere {_d(frm)} - {_d(to)}: hut closed or "
            f"period not open for online booking yet (or sold out every night)",
            options,
        )
    detail = f"no bookable stay covering {_d(night)} for {guests}"
    if not any(s[0] > night for s in all_stays):
        detail += (f"; nothing bookable online from {_d(night)} to {_d(to)} either "
                   f"(sold out, or not yet released online)")
    return CheckResult(Status.FULL, detail, options)


# --- request helpers ---------------------------------------------------------------

def _window(night: dt.date, lookback: int) -> tuple[dt.date, dt.date]:
    """Calendar-month window like the widget (from=1st, to=last day of month), widened
    backwards so stays that start up to `lookback` days before `night` are seen."""
    first = night.replace(day=1)
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    return min(first, night - dt.timedelta(days=lookback)), nxt - dt.timedelta(days=1)


def _layouts(guests: int, max_adults: int) -> list[tuple[str, list[list[int]]]]:
    if guests < 1:
        raise ValueError("guests must be >= 1")
    out = []
    if guests <= max_adults:
        out.append((f"1 room for {guests}", [[ADULT_AGE] * guests]))
    if guests > 1:
        out.append((f"{guests} x 1-person units (dorm beds/singles)", [[ADULT_AGE]] * guests))
    return out


def _guests_json(rooms: list[list[int]]) -> str:
    return json.dumps(rooms, separators=(",", ":"))  # == JSON.stringify


def _parse_availabilities(data: Any, url: str) -> list[Stay]:
    if not isinstance(data, list):
        raise FetchError(f"unexpected availabilities payload from {url}: {type(data).__name__}")
    stays: list[Stay] = []
    try:
        for item in data:
            arr = dt.date.fromisoformat(item["date"])
            for d in item["departures"]:
                stays.append((arr, dt.date.fromisoformat(d["departure"]), str(d["rule"])))
    except (KeyError, TypeError, ValueError) as e:
        raise FetchError(f"unparseable availabilities from {url}: {e!r}") from e
    return stays


# --- summarising -------------------------------------------------------------------

def _stay_rank(stay: Stay, night: dt.date) -> tuple[int, int]:
    arr, dep, _ = stay
    return ((dep - arr).days, 0 if arr == night else 1)


def _one_night_rule(per_layout, night: dt.date) -> str | None:
    rules = {s[2] for _, _, cov, _ in per_layout for s in cov
             if s[0] == night and s[1] == night + dt.timedelta(days=1)}
    return OK if OK in rules else (min(rules) if rules else None)


def _d(day: dt.date) -> str:
    return day.strftime("%d %b %Y").lstrip("0")


def _span(stay: Stay) -> str:
    arr, dep, _ = stay
    n = (dep - arr).days
    return f"{arr.isoformat()} -> {dep.isoformat()} ({n} night{'s' if n != 1 else ''})"


def _layout_line(label: str, covering: list[Stay], night: dt.date) -> str:
    if not covering:
        return f"{label}: nothing covering {night.isoformat()}"
    ok = sorted((s for s in covering if s[2] == OK), key=lambda s: _stay_rank(s, night))
    parts = []
    if ok:
        parts.append("shortest bookable " + _span(ok[0]))
    refused = sorted({RULE_TEXT.get(s[2], s[2]) for s in covering if s[2] != OK})
    if refused:
        parts.append("some stays refused: " + ", ".join(refused))
    return f"{label}: " + "; ".join(parts)


def _room_summary(fetch: Fetch, base: str, pid: int, sid: int, p: dict,
                  rooms: list[list[int]], stay: Stay) -> str:
    """Best-effort: room types / free units / cheapest total for the chosen stay.
    Availability is already established, so failures here never mask it."""
    lang = str(p.get("lang", "en"))
    try:
        offers = fetch(
            "GET",
            f"{base}/properties/{pid}/offers",
            params={
                "guests": _guests_json(rooms),
                "sourceId": sid,
                "from": stay[0].isoformat(),
                "to": stay[1].isoformat(),
                "lang": lang,
                "correlationId": secrets.token_urlsafe(18)[:23],
                "guestCount": len(rooms) + 1,  # sic: the widget sends rooms + 1
                "maxAdults": int(p.get("max_adults", 4)),
                "maxChildren": int(p.get("max_children", 3)),
            },
            headers=HEADERS,
        ).json()
        free = {r["room_id"]: r.get("room_free") for r in offers.get("rooms", [])}
        cheapest: dict[Any, float] = {}
        for r in offers.get("rates", []):
            if r.get("room_seq", 1) == 1 and r.get("price_total") is not None:
                rid = r["room_id"]
                cheapest[rid] = min(cheapest.get(rid, r["price_total"]), r["price_total"])
        if not free:
            return ""
        names: dict[Any, str] = {}
        try:
            for r in fetch("GET", f"{base}/properties/{pid}/rooms",
                           params={"lang": lang, "sourceId": sid}, headers=HEADERS).json():
                names[r["room_id"]] = str(r.get("title") or r["room_id"]).strip()
        except (FetchError, KeyError, TypeError, AttributeError):
            pass
        bits = []
        for rid, n in free.items():
            s = f"{names.get(rid, f'room {rid}')} x{n} free"
            if rid in cheapest:
                s += f" from EUR {cheapest[rid]:g}" + (" per unit" if len(rooms) > 1 else "")
            bits.append(s)
        return ", ".join(bits)
    except (FetchError, KeyError, TypeError, AttributeError, ValueError):
        return ""
