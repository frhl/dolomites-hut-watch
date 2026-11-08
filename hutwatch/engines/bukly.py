"""Bukly booking engine (https://<slug>.bukly.com), e.g. Rifugio Scotoni, Col Gallina, Averau.

The engine is a Laravel + Inertia.js app. The page's own search bar does

    GET https://<slug>.bukly.com/booking?rooms=<occupancy>&checkin=YYYY-MM-DD&checkout=YYYY-MM-DD

(an Inertia GET: `router.get(path, {rooms, checkin, checkout, promo})`), and the server
answers with the whole page; its state is JSON inside
`<script data-page="app" type="application/json">`. `rooms` encodes one room request per
`|`-separated item, each `"<adults>"` or `"<adults>-<childAge>,<childAge>"`; "2" = one
request for 2 adults. Nothing is created by this GET (selecting a room is a separate POST
we never send).

Relevant page props:
- props.bookingEngine.form: echo of the search (checkin, checkout, rooms, dateConfirmed).
- props.allocations[]: one entry per room request; `assignments[].room.ratePlans[]` carry
  `sell_type` ("bed" = dorm sold per bed, "room" = whole room), `minAvailability` (free
  beds resp. free rooms, minimum over the searched nights), `maxGuests.total` and a
  per-night `price[]` list. The server lists rooms with ANY free bed, even fewer than the
  requested guests (observed: 1 free bed listed for a 2-adult search), so capacity must be
  checked here.
- props.bookingEngine.calendarRestrictions: sellable window (minDate..maxDate) and
  `unavailableDates` / `checkinRestricted` / `checkoutRestricted`. This calendar is
  occupancy-independent (a night with 1 free bed is "available"), and it does NOT tell a
  sold-out night from a closed/not-for-sale one. calendarMinPrices.prices has a min price
  for exactly the calendar-available nights.

The public UI has no minimum-stay message: a rate failing a stay rule is simply not listed.
So "1-night search empty although the calendar shows beds that night" is treated as a
stay-rule refusal and retried with longer windows; MIN_STAY only if those give nothing.

Reusable pieces (e.g. for an opening watch): `base_url`, `search_params`, `search`,
`parse_search`, `calendar_nights`, `fetch_calendar`, `offers_for_night`, `assess`.

hut.params:
    slug       "scotoni"            -> https://scotoni.bukly.com   (or)
    base_url   "https://reservas.example.com"  for custom domains
    hotel_id   4820                 optional sanity check against the page's hotel id
    allow_split  True               count beds spread over several rooms as available
    max_window_tries  2             extra requests allowed for the stay-rule retry
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.http import Fetch, FetchError, Response

PAGE_COMPONENT = "BookingEngine/resources/js/Pages/Index"
_SCRIPT_RE = re.compile(r"<script\b[^>]*\bdata-page=[\"']app[\"'][^>]*>(.*?)</script>", re.S | re.I)
_DIV_RE = re.compile(r"<div\b[^>]*\bdata-page=\"([^\"]*)\"", re.S | re.I)
_LOCALES = ("en-US", "it-IT", "de-DE")
_CURRENCY = {"EUR": "€", "CHF": "CHF ", "USD": "$"}

# Calendar night states (calendar_nights)
NIGHT_AVAILABLE = "available"      # calendar lists >= 1 free bed/room that night
NIGHT_UNAVAILABLE = "unavailable"  # sold out OR closed (Bukly does not distinguish)
NIGHT_NOT_ON_SALE = "not_on_sale"  # outside the sellable window minDate..maxDate

# Longer stays tried when a 1-night search is refused: (check-in offset, nights)
_STAY_WINDOWS = ((0, 2), (-1, 2), (0, 3))
_DAY = dt.timedelta(days=1)


# --------------------------------------------------------------------------- request

def base_url(hut: Hut) -> str:
    p = hut.params or {}
    if p.get("base_url"):
        return str(p["base_url"]).rstrip("/")
    slug = p.get("slug")
    if not slug:
        raise ValueError(f"{hut.id}: bukly engine needs params['slug'] or params['base_url']")
    return f"https://{slug}.bukly.com"


def search_params(checkin: dt.date, checkout: dt.date, guests: int) -> dict[str, str]:
    """Query string of the page's own search: one room request for `guests` adults."""
    if guests < 1:
        raise ValueError("guests must be >= 1")
    if checkout <= checkin:
        raise ValueError("checkout must be after checkin")
    return {"rooms": str(guests), "checkin": checkin.isoformat(), "checkout": checkout.isoformat()}


# --------------------------------------------------------------------------- parsing

@dataclass
class Calendar:
    min_date: dt.date
    max_date: dt.date
    unavailable: frozenset[str]
    checkin_restricted: frozenset[str]
    checkout_restricted: frozenset[str]
    min_prices: dict[str, float]


@dataclass
class Search:
    url: str
    hotel_id: Any
    hotel_name: str
    currency: str
    form: dict[str, Any]
    calendar: Calendar
    allocations: list[dict[str, Any]]
    combinations: Any = None
    hotel_restrictions: Any = None

    def echoes(self, checkin: dt.date, checkout: dt.date, guests: int) -> bool:
        """True if the server answered for exactly these dates and occupancy."""
        f = self.form
        return (str(f.get("checkin")) == checkin.isoformat()
                and str(f.get("checkout")) == checkout.isoformat()
                and str(f.get("rooms")) == str(guests)
                and f.get("dateConfirmed", True) is not False)


@dataclass
class Offer:
    room: str
    sell_type: str          # "bed" (dorm, sold per bed) or "room" (whole room)
    free: int               # free beds ("bed") or free rooms ("room"), min over the stay
    capacity: int           # persons per unit: 1 per bed, maxGuests for a room
    price: float | None     # price for the night: per bed ("bed") or per room ("room")
    currency: str = "EUR"

    @property
    def beds(self) -> int:
        return self.free * self.capacity

    def fits(self, guests: int) -> bool:
        if self.sell_type == "bed":
            return self.free >= guests
        return self.free >= 1 and self.capacity >= guests

    def describe(self) -> str:
        unit = "bed" if self.sell_type == "bed" else "room"
        s = f"{self.room}: {self.free} {unit}{'' if self.free == 1 else 's'}"
        if unit == "room":
            s += f" (sleeps {self.capacity})"
        if self.price is not None:
            sym = _CURRENCY.get(self.currency, self.currency + " ")
            s += f" {sym}{self.price:g}/{unit}"
        return s


def _date(v: Any, what: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError as e:
        raise FetchError(f"bad {what} {v!r} in Bukly page") from e


def _page_json(resp: Response) -> dict[str, Any]:
    text = resp.text()
    if "json" in resp.content_type.lower() or text.lstrip().startswith("{"):
        return resp.json()                     # X-Inertia style JSON (not used by check())
    m = _SCRIPT_RE.search(text)
    raw = m.group(1) if m else None
    if raw is None:
        m = _DIV_RE.search(text)               # older Inertia: <div id="app" data-page="...">
        raw = html.unescape(m.group(1)) if m else None
    if raw is None:
        raise FetchError(f"no Inertia page data in {resp.url}")
    try:
        return json.loads(raw)
    except ValueError as e:
        raise FetchError(f"invalid page JSON from {resp.url}: {e}") from e


def parse_search(resp: Response) -> Search:
    """Parse a /booking page (HTML or Inertia JSON). Raises FetchError if the shape is off."""
    page = _page_json(resp)
    props = page.get("props") if isinstance(page, dict) else None
    comp = str(page.get("component", "")) if isinstance(page, dict) else ""
    if not isinstance(props, dict) or PAGE_COMPONENT not in comp:
        raise FetchError(f"unexpected Bukly page component {comp!r} from {resp.url}")
    be = props.get("bookingEngine")
    if not isinstance(be, dict) or not isinstance(be.get("form"), dict):
        raise FetchError(f"no bookingEngine.form in Bukly page from {resp.url}")
    cr = be.get("calendarRestrictions")
    if not isinstance(cr, dict) or "minDate" not in cr or "maxDate" not in cr:
        raise FetchError(f"no calendarRestrictions in Bukly page from {resp.url}")
    allocations = props.get("allocations", be.get("allocations"))
    if not isinstance(allocations, list):
        raise FetchError(f"no allocations list in Bukly page from {resp.url}")
    prices = {}
    for d, p in ((be.get("calendarMinPrices") or {}).get("prices") or {}).items():
        if isinstance(p, dict) and p:
            prices[d] = next(iter(p.values()))
    hotel = be.get("hotel") or {}
    cal = Calendar(
        min_date=_date(cr["minDate"], "minDate"),
        max_date=_date(cr["maxDate"], "maxDate"),
        unavailable=frozenset(cr.get("unavailableDates") or ()),
        checkin_restricted=frozenset(cr.get("checkinRestricted") or ()),
        checkout_restricted=frozenset(cr.get("checkoutRestricted") or ()),
        min_prices=prices,
    )
    return Search(
        url=resp.url,
        hotel_id=hotel.get("id"),
        hotel_name=str(hotel.get("name") or "").strip(),
        currency=str(hotel.get("currency") or "EUR"),
        form=be["form"],
        calendar=cal,
        allocations=allocations,
        combinations=be.get("combinations"),
        hotel_restrictions=be.get("hotelRestrictions"),
    )


def search(hut: Hut, checkin: dt.date, checkout: dt.date, guests: int, fetch: Fetch) -> Search:
    """One availability request (the page's own search), parsed."""
    resp = fetch("GET", base_url(hut) + "/booking", params=search_params(checkin, checkout, guests))
    s = parse_search(resp)
    want = (hut.params or {}).get("hotel_id")
    if want is not None and str(s.hotel_id) != str(want):
        raise FetchError(f"{hut.id}: Bukly page is hotel {s.hotel_id}, expected {want}")
    return s


# --------------------------------------------------------------------------- interpretation

def calendar_nights(s: Search, start: dt.date, end: dt.date) -> dict[dt.date, tuple[str, float | None]]:
    """Per-night calendar state for check-in dates start..end (exclusive): (state, min price).

    Occupancy-independent: "available" means >= 1 free unit, not >= guests.
    """
    out = {}
    d = start
    while d < end:
        iso = d.isoformat()
        if d < s.calendar.min_date or d > s.calendar.max_date:
            state = NIGHT_NOT_ON_SALE
        elif iso in s.calendar.unavailable:
            state = NIGHT_UNAVAILABLE
        else:
            state = NIGHT_AVAILABLE
        out[d] = (state, s.calendar.min_prices.get(iso))
        d += _DAY
    return out


def fetch_calendar(hut: Hut, start: dt.date, end: dt.date, fetch: Fetch,
                   guests: int = 1) -> dict[dt.date, tuple[str, float | None]]:
    """One request -> calendar_nights for start..end (the calendar covers the whole window)."""
    return calendar_nights(search(hut, start, start + _DAY, guests, fetch), start, end)


def _name(names: Any, fallback: str) -> str:
    if isinstance(names, dict):
        for loc in _LOCALES:
            if names.get(loc):
                return str(names[loc]).strip()
        for v in names.values():
            if v:
                return str(v).strip()
    elif names:
        return str(names).strip()
    return fallback


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def offers_for_night(s: Search, night: dt.date) -> list[Offer]:
    """Bookable room types in the search result that cover `night` (one Offer per room)."""
    iso = night.isoformat()
    by_room: dict[Any, Offer] = {}
    for req in s.allocations:
        for a in (req or {}).get("assignments") or ():
            room = (a or {}).get("room") or {}
            name = _name(room.get("name"), f"room {room.get('id')}")
            for rp in room.get("ratePlans") or ():
                restr = rp.get("restrictions")
                if isinstance(restr, dict) and any(v is False for v in restr.values()):
                    continue  # rate shown as unavailable (admin/"show unavailable" views)
                nights = {str(p.get("date")): p for p in rp.get("price") or () if isinstance(p, dict)}
                if nights and iso not in nights:
                    continue
                p = nights.get(iso, {})
                price = p.get("discounted_price", p.get("basePrice"))
                sell = "bed" if rp.get("sell_type") == "bed" else "room"
                free = _int(rp.get("minAvailability", room.get("minAvailability")))
                cap = 1 if sell == "bed" else max(1, _int((rp.get("maxGuests") or {}).get("total"),
                                                           _int(room.get("beds"), 1)))
                if free <= 0:
                    continue
                o = Offer(name, sell, free, cap, float(price) if price is not None else None, s.currency)
                key = (room.get("id"), sell)
                prev = by_room.get(key)
                if prev is None or o.beds > prev.beds or (
                        o.beds == prev.beds and o.price is not None
                        and (prev.price is None or o.price < prev.price)):
                    by_room[key] = o
    return list(by_room.values())


def assess(offers: list[Offer], guests: int, allow_split: bool = True) -> tuple[bool, str]:
    """(enough beds for `guests`?, one-line summary)."""
    if not offers:
        return False, "no rooms offered"
    fitting = [o for o in offers if o.fits(guests)]
    lines = "; ".join(o.describe() for o in (fitting or offers))
    if fitting:
        return True, lines
    total = sum(o.beds for o in offers)
    if total >= guests:
        if allow_split:
            return True, f"only split across rooms ({total} beds): {lines}"
        return False, f"no single room for {guests} ({total} beds split across rooms): {lines}"
    return False, f"only {total} bed{'' if total == 1 else 's'} free for {guests}: {lines}"


def _extras(s: Search) -> str:
    bits = []
    if s.hotel_restrictions:
        bits.append(f"hotelRestrictions={json.dumps(s.hotel_restrictions)[:120]}")
    if s.combinations:
        bits.append("engine suggested alternative room combinations")
    return (" [" + "; ".join(bits) + "]") if bits else ""


# --------------------------------------------------------------------------- engine entry point

def check(hut: Hut, night: dt.date, guests: int, fetch: Fetch) -> CheckResult:
    p = hut.params or {}
    allow_split = bool(p.get("allow_split", True))
    checkout = night + _DAY
    s = search(hut, night, checkout, guests, fetch)
    if not s.echoes(night, checkout, guests):
        return CheckResult(Status.UNKNOWN, f"engine answered for a different search: {s.form}")

    if s.allocations:
        offers = offers_for_night(s, night)
        ok, summary = assess(offers, guests, allow_split)
        lines = [o.describe() for o in offers]
        if ok:
            return CheckResult(Status.AVAILABLE, summary + _extras(s), lines,
                               split=summary.startswith("only split across rooms"))
        if offers:
            return CheckResult(Status.FULL, summary + _extras(s), lines)
        return CheckResult(Status.UNKNOWN, "rooms listed but none usable for the night" + _extras(s))

    cal = s.calendar
    iso = night.isoformat()
    if night < cal.min_date or night > cal.max_date:
        return CheckResult(Status.CLOSED, f"not on sale: outside booking window "
                                          f"{cal.min_date}..{cal.max_date}")
    if s.combinations:
        return CheckResult(Status.UNKNOWN, "no rooms offered, but" + _extras(s))
    if iso in cal.unavailable:
        return CheckResult(Status.FULL, "no beds offered; calendar marks night unavailable "
                                        "(sold out or closed - Bukly does not distinguish)" + _extras(s))

    # Calendar shows free beds but the 1-night search listed nothing: stay rule
    # (min stay / no arrival). Read the night from a longer stay instead.
    tried = []
    budget = _int(p.get("max_window_tries", 2), 2)
    for start_off, n in _STAY_WINDOWS:
        if budget <= 0:
            break
        ci = night + dt.timedelta(days=start_off)
        co = ci + dt.timedelta(days=n)
        stay = calendar_nights(s, ci, co)
        if any(state != NIGHT_AVAILABLE for state, _ in stay.values()):
            continue
        if ci.isoformat() in cal.checkin_restricted:
            continue
        budget -= 1
        w = search(hut, ci, co, guests, fetch)
        if not w.echoes(ci, co, guests):
            tried.append(f"{ci}->{co}: engine answered a different search")
            continue
        offers = offers_for_night(w, night)
        ok, summary = assess(offers, guests, allow_split)
        if ok:
            return CheckResult(Status.AVAILABLE,
                               f"{summary} (1-night stay refused; bookable as {n}-night stay {ci}->{co})",
                               [o.describe() for o in offers],
                               split=summary.startswith("only split across rooms"))
        tried.append(f"{ci}->{co}: {summary}")
    detail = "1-night stay refused although calendar lists free beds"
    detail += ("; tried " + " | ".join(tried)) if tried else "; no longer stay with calendar availability"
    return CheckResult(Status.MIN_STAY, detail)
