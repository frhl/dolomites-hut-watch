"""Engine for Rifugio Nuvolau (rifugionuvolau.it): VikBooking (WordPress plugin, v1.8.15).

Observed 2026-11-08 (see tests/fixtures/nuvolau/README.md):

- "book now" on /en/booking/ leads to /en/booking-form/, a page holding the VikBooking
  search view inside <div class="wrap plugin-container">. In the plugin source
  (site/views/vikbooking/tmpl/default.php, tag 1.8.15) that view prints only
  VikBooking::getDisabledBookingMsg() when the global "allow bookings" switch is off,
  else <div class="vbdivsearch vbo-search-mainview"><form ...task=search...>.
  Today the container holds just "Rooms closed, see you in June 2027!".
  -> FORM STATE = the master on/off switch for selling beds.
- The engine's own calendar is the VikBooking "availability" view (/en/availability/).
  Its month <select> submits month=<UTC-midnight unix ts of day 1>; the same parameter
  works as a plain GET (verified: month=1811808000 rendered June 2027), so we GET:
      /en/availability/?view=availability&room_ids[0]=4&...&room_ids[4]=7&showtype=2&month=TS
  It takes no guest count and no stay length: one row per room type, one cell per
  NIGHT (template counts bookings with checkin <= day < checkout):
      <td class="vbo-occupied-cell[ vbo-partially-cell]" data-cell-date="24/06/2027" ...>
        <span class="vbo-availability-day-container" data-units-booked="B"
              data-units-left="L">L</span></td>
      <td class="vbo-free-cell" data-cell-date=".." data-cell-ts=".."></td>   (no span)
  Each "room" is a bed type ("Bed in a shared N-bed room") whose units are beds:
  3+4+4+5+8 = 24, the hut's stated 24 beds. Free beds for a night = sum over room
  types; the `guests` threshold is applied here. Closed season and sold out look the
  same (all units booked: closures are stored as bookings), hence the form check.

Status mapping (check):
  form disabled                        -> CLOSED  (1 request; calendar not fetched)
  form live, free beds >= guests       -> AVAILABLE
  form live, free beds <  guests       -> FULL    (incl. dates not yet released)
  unrecognised cell class on the night -> UNKNOWN
MIN_STAY never: the calendar shows no stay rules (VikBooking restrictions may still
refuse a 1-night stay at checkout; not observable while bookings are disabled).

hut.params (all optional; defaults below are Nuvolau's observed values):
    form_url          VikBooking search-view page (disabled message lives here)
    availability_url  VikBooking availability-view page
    room_ids          room-type ids, in the order the page's own form sends them
    room_units        {room_id: beds}, used only for a fully free cell (no span)
    probe_month       "YYYY-MM" month that booking_open() scans for free beds
    date_order        "dmy" | "mdy" | "ymd", order of data-cell-date
"""

from __future__ import annotations

import calendar
import datetime as dt
import html
import re
from dataclasses import dataclass, field
from typing import Any

from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.http import Fetch, FetchError

DEFAULTS: dict[str, Any] = {
    "form_url": "https://rifugionuvolau.it/en/booking-form/",
    "availability_url": "https://rifugionuvolau.it/en/availability/",
    "room_ids": [4, 6, 8, 5, 7],
    "room_units": {"4": 3, "6": 4, "8": 4, "5": 5, "7": 8},
    "probe_month": "2027-06",
    "date_order": "dmy",
}

_CONTAINER_RE = re.compile(r'<div\s+class="wrap\s+plugin-container"\s*>', re.I)
_SEARCH_VIEW_RE = re.compile(r'class="vbdivsearch\s+vbo-search-mainview', re.I)
_ROOM_SPLIT_RE = re.compile(r'<div\s+class="vbo-availability-room-container"\s*>', re.I)
_H4_RE = re.compile(r"<h4>(.*?)</h4>", re.S | re.I)
_TABLE_RE = re.compile(r'<table\b[^>]*\bid="vbo-av-table-(\d+)"[^>]*>(.*?)</table>', re.S | re.I)
_CELL_RE = re.compile(
    r'<td\s+class="([^"]*)"\s+data-cell-date="([^"]*)"\s+data-cell-ts="(\d+)"\s*>(.*?)</td>',
    re.S | re.I,
)
_UNITS_RE = re.compile(r'data-units-booked="(\d+)"\s+data-units-left="(-?\d+)"')


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _params(hut: Hut) -> dict[str, Any]:
    return {**DEFAULTS, **(hut.params or {})}


# --- booking form (master switch) ---------------------------------------------------

@dataclass
class FormState:
    enabled: bool
    message: str = ""  # the disabled-booking message, when disabled


def parse_form(text: str) -> FormState:
    """VikBooking search-view page -> enabled / disabled(message). FetchError otherwise."""
    m = _CONTAINER_RE.search(text)
    if not m:
        raise FetchError("nuvolau: no VikBooking <div class=\"wrap plugin-container\"> on form page")
    rest = text[m.end():]
    if _SEARCH_VIEW_RE.search(rest):
        return FormState(True)
    inner = rest.split("</div>", 1)[0]
    if re.search(r"<(form|input|select|script)\b", inner, re.I):
        raise FetchError("nuvolau: form page has a plugin container that is neither the "
                         "search view nor a plain disabled message")
    msg = _clean(inner)
    if not msg:
        raise FetchError("nuvolau: empty VikBooking container on form page")
    return FormState(False, msg)


# --- availability calendar ----------------------------------------------------------

@dataclass
class Cell:
    classes: list[str]
    booked: int | None   # None: no span (fully free cell)
    left: int | None


@dataclass
class Room:
    id: int
    name: str
    cells: dict[dt.date, Cell] = field(default_factory=dict)
    units: int | None = None  # beds of this type (from spans, else params)

    def free(self, night: dt.date) -> int | None:
        """Free beds that night; None if the cell is not understood."""
        c = self.cells[night]
        if c.left is not None:
            return max(c.left, 0)
        if "vbo-free-cell" in c.classes:
            return self.units if self.units is not None else 1  # [ASSUMPTION] >= 1
        if "vbo-occupied-cell" in c.classes:
            return 0
        return None


@dataclass
class Month:
    year: int
    month: int
    rooms: list[Room]

    @property
    def label(self) -> str:
        return dt.date(self.year, self.month, 1).strftime("%B %Y")

    @property
    def total_units(self) -> int | None:
        u = [r.units for r in self.rooms]
        return None if any(x is None for x in u) else sum(u)  # type: ignore[arg-type]

    def nights(self) -> list[dt.date]:
        return sorted({d for r in self.rooms for d in r.cells})

    def free_by_room(self, night: dt.date) -> list[tuple[Room, int | None]]:
        if any(night not in r.cells for r in self.rooms):
            raise FetchError(f"nuvolau: {night} missing from the {self.label} calendar")
        return [(r, r.free(night)) for r in self.rooms]

    def free_total(self, night: dt.date) -> int | None:
        vals = [f for _, f in self.free_by_room(night)]
        return None if any(v is None for v in vals) else sum(vals)  # type: ignore[arg-type]


def _parse_date(s: str, order: str) -> dt.date:
    parts = re.split(r"[/.\-]", s.strip())
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise FetchError(f"nuvolau: unparseable data-cell-date {s!r}")
    a, b, c = (int(p) for p in parts)
    try:
        if order == "ymd" or len(parts[0]) == 4:
            return dt.date(a, b, c)
        if order == "mdy":
            return dt.date(c, a, b)
        return dt.date(c, b, a)
    except ValueError as e:
        raise FetchError(f"nuvolau: bad data-cell-date {s!r}: {e}") from e


def parse_month(text: str, room_units: dict | None = None, date_order: str = "dmy") -> Month:
    """Availability view -> Month. Raises FetchError if the page isn't recognisable."""
    room_units = {str(k): int(v) for k, v in (room_units or {}).items()}
    rooms: list[Room] = []
    for chunk in _ROOM_SPLIT_RE.split(text)[1:]:
        tm = _TABLE_RE.search(chunk)
        if not tm:
            continue
        hm = _H4_RE.search(chunk[: tm.start()])
        room = Room(id=int(tm.group(1)), name=_clean(hm.group(1)) if hm else f"room {tm.group(1)}")
        seen_units: list[int] = []
        for cls, date_s, _ts, inner in _CELL_RE.findall(tm.group(2)):
            um = _UNITS_RE.search(inner)
            booked, left = (int(um.group(1)), int(um.group(2))) if um else (None, None)
            if um:
                seen_units.append(booked + left)
            room.cells[_parse_date(date_s, date_order)] = Cell(cls.split(), booked, left)
        if not room.cells:
            raise FetchError(f"nuvolau: availability table for room {room.id} has no day cells")
        room.units = max(seen_units) if seen_units else room_units.get(str(room.id))
        rooms.append(room)
    if not rooms:
        raise FetchError("nuvolau: no VikBooking availability tables in response")
    months = {(d.year, d.month) for r in rooms for d in r.cells}
    if len(months) != 1:
        raise FetchError(f"nuvolau: availability cells span several months: {sorted(months)}")
    (year, month), = months
    return Month(year, month, rooms)


def month_ts(year: int, month: int) -> int:
    """Value the page's own month <select> sends: unix ts of day 1, 00:00 UTC."""
    return calendar.timegm((year, month, 1, 0, 0, 0))


def availability_params(room_ids: list, year: int, month: int) -> dict[str, Any]:
    """Same query the page's own month form uses (room_ids[i] indexed, showtype=2)."""
    p: dict[str, Any] = {"view": "availability"}
    for i, rid in enumerate(room_ids):
        p[f"room_ids[{i}]"] = int(rid)
    p["showtype"] = 2
    p["month"] = month_ts(year, month)
    return p


def _get(fetch: Fetch, url: str, **kw):
    resp = fetch("GET", url, **kw)
    if resp.status >= 400:
        raise FetchError(f"HTTP {resp.status} from {resp.url}")
    return resp


def fetch_form(fetch: Fetch, p: dict[str, Any]) -> FormState:
    return parse_form(_get(fetch, p["form_url"]).text())


def fetch_month(fetch: Fetch, p: dict[str, Any], year: int, month: int) -> Month:
    resp = _get(fetch, p["availability_url"], params=availability_params(p["room_ids"], year, month))
    mo = parse_month(resp.text(), p.get("room_units"), p.get("date_order", "dmy"))
    if (mo.year, mo.month) != (year, month):
        raise FetchError(f"nuvolau: asked for {year}-{month:02d}, calendar shows {mo.label}")
    return mo


# --- public API ---------------------------------------------------------------------

def _room_line(room: Room, free: int, dup: bool) -> str:
    name = f"{room.name} #{room.id}" if dup else room.name  # two rooms are "4-bed"
    return f"{name}: {free} free" + (f" of {room.units}" if room.units is not None else "")


def classify(month: Month, night: dt.date, guests: int) -> CheckResult:
    pairs = month.free_by_room(night)
    bad = [r for r, f in pairs if f is None]
    if bad:
        cls = " ".join(bad[0].cells[night].classes)
        return CheckResult(Status.UNKNOWN, f"unrecognised calendar cell class={cls!r} on {night}")
    names = [r.name for r in month.rooms]
    free = [(r, f) for r, f in pairs if f]  # type: ignore[misc]
    total = sum(f for _, f in free)
    options = [_room_line(r, f, names.count(r.name) > 1) for r, f in free]
    units = month.total_units
    of = f"/{units}" if units is not None else ""
    if total >= guests:
        return CheckResult(Status.AVAILABLE, f"{total}{of} beds free: " + "; ".join(options), options,
                           split=max(f for _, f in free) < guests)
    if total == 0:
        return CheckResult(Status.FULL, f"no bed free (0{of}; sold out, or night not released yet)")
    return CheckResult(Status.FULL, f"only {total}{of} bed(s) free, need {guests}: "
                       + "; ".join(options), options)


def check(hut: Hut, night: dt.date, guests: int, fetch: Fetch) -> CheckResult:
    p = _params(hut)
    form = fetch_form(fetch, p)
    if not form.enabled:
        return CheckResult(Status.CLOSED, f"bookings disabled on site: {form.message!r}")
    return classify(fetch_month(fetch, p, night.year, night.month), night, guests)


def booking_open(hut: Hut, fetch: Fetch) -> tuple[bool, str]:
    """True once VikBooking's booking switch is on (search form replaces the disabled
    message), even if every night is already taken. 2 requests: form + probe month."""
    p = _params(hut)
    year, month = (int(x) for x in str(p["probe_month"]).split("-"))
    form = fetch_form(fetch, p)
    try:
        mo = fetch_month(fetch, p, year, month)
    except FetchError as e:
        if form.enabled:  # opening-day overload must not hide the one signal that matters
            return True, f"booking form is live; {year}-{month:02d} calendar fetch failed: {e}"
        raise
    free = [(d, n) for d in mo.nights() if (n := mo.free_total(d))]
    first = f"{free[0][0].isoformat()} ({free[0][1]} beds)" if free else ""
    if form.enabled:
        if free:
            return True, (f"booking form is live; first bookable {year} date seen: {first}; "
                          f"{len(free)} night(s) with free beds in {mo.label}")
        return True, (f"booking form is live, but no free bed on any night of {mo.label} "
                      "(sold out, or those dates not released yet)")
    if free:
        return False, (f"bookings still disabled ({form.message!r}) but the {mo.label} calendar "
                       f"already shows free beds from {first}: opening looks imminent")
    return False, (f"bookings disabled: {form.message!r}; {mo.label} calendar fully blocked "
                   f"({len(mo.nights())} nights, 0 free beds)")
