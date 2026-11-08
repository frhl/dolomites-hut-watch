"""Engine for the "disponibilita.php" real-time bed calendar.

Used by Rifugio Lagazuoi (rifugiolagazuoi.com/EN/disponibilita.php) and Rifugio
Tissi (rifugiotissi.com/EN/disponibilita.php). Observed 2026-11-08:

- There is no XHR/JSON API. A plain GET of the page returns full HTML containing a
  server-rendered month table <table id="TabDisp">. The page's own month arrows link
  to ``?prm=<P>&chm=<+1|-1>``; the month rendered is month index P+C counted from
  January of the server's current year (no query = current month, whose arrows carry
  prm=<current month number>). prm=11&chm=7 and prm=17&chm=1 both rendered June 2027.
  Nothing is held or booked; no cookies are needed.
- Each day is <td class="libero"> (green: some beds free) or <td class="chiuso">
  (grey: "not available"). A green day has a modal <div class="... reveal"
  id="giorno-D"> with one <div class="dettagli"> per accommodation type, e.g.
      "Dormitories with bunk beds n. 16 beds available"           -> 16 beds
      "Room with 4 beds n. 28 posti letto disponibili"             -> 28 beds
      "n. 1 Quadruple room ...<br/><i title="N° max persone: 4">"  -> 1 room x 4
      "Private room with 1 bunk-beds<br/><i title="... 2">"        -> 1 room x 2
- The calendar takes no guest count and has no minimum-stay rule (it is per night),
  so MIN_STAY never applies; the `guests` threshold is applied here.
- Grey does not distinguish "sold out" from "closed season" (closed November 2026
  and sold-out June nights look identical), so grey is reported as FULL, never CLOSED.

hut.params:
    url  (str, optional)  calendar page URL; defaults to hut.booking_url.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.http import Fetch, FetchError

_MONTH_NAMES = [
    ("january", "gennaio", "januar"),
    ("february", "febbraio", "februar"),
    ("march", "marzo", "märz", "maerz"),
    ("april", "aprile"),
    ("may", "maggio", "mai"),
    ("june", "giugno", "juni"),
    ("july", "luglio", "juli"),
    ("august", "agosto"),
    ("september", "settembre"),
    ("october", "ottobre", "oktober"),
    ("november", "novembre"),
    ("december", "dicembre", "dezember"),
]
MONTHS = {name: i for i, names in enumerate(_MONTH_NAMES, start=1) for name in names}

_TABLE_RE = re.compile(r'<table\b[^>]*\bid="TabDisp"[^>]*>(.*?)</table>', re.S | re.I)
_HEADER_RE = re.compile(r'<th\b[^>]*\bcolspan="5"[^>]*>(.*?)</th>', re.S | re.I)
_TD_RE = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.S | re.I)
_CLASS_RE = re.compile(r'\bclass="([^"]*)"', re.I)
_REVEAL_RE = re.compile(
    r'<div\b[^>]*\bid="giorno-(\d+)"[^>]*>(.*?)(?=<button\b|<td\b|</tr>|$)', re.S | re.I
)
_DETTAGLI_RE = re.compile(r'<div\s+class="dettagli"\s*>(.*?)</div>', re.S | re.I)
_MAXP_RE = re.compile(r"max\s+persone\s*:\s*(\d+)", re.I)
_ROOM_HEAD_RE = re.compile(r"n\.\s*(\d+)\s+(.+)", re.S)
# Bed line: the LAST "n. <digits>" followed only by non-digit text, e.g.
# "Dormitory, 16 beds, ... outside. n. 16 posti letto disponibili" -> 16.
_BEDS_RE = re.compile(r"(?P<label>.*)\bn\.\s*(?P<n>\d+)\b[^\d]*$", re.S)


def _today() -> dt.date:
    """Separate function so tests can pin the clock."""
    return dt.date.today()


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


@dataclass
class Offer:
    label: str
    places: int  # persons this accommodation type can take
    line: str    # human summary (full name)
    short: str   # same, name truncated, for the one-line detail


@dataclass
class Day:
    state: str                                   # css class, e.g. "libero" / "chiuso"
    details: list[str] = field(default_factory=list)  # raw <div class="dettagli"> HTML


@dataclass
class Month:
    year: int
    month: int
    label: str          # header as shown, e.g. "June 2027"
    days: dict[int, Day]


def parse_month(text: str) -> Month:
    """Parse the TabDisp month table. Raises FetchError if the page isn't recognisable."""
    m = _TABLE_RE.search(text)
    if not m:
        raise FetchError("disponibilita.php: no <table id=\"TabDisp\"> in response")
    table = m.group(1)
    hm = _HEADER_RE.search(table)
    label = _clean(hm.group(1)) if hm else ""
    parts = re.fullmatch(r"(\S+)\s+(\d{4})", label)
    if not parts or parts.group(1).lower() not in MONTHS:
        raise FetchError(f"disponibilita.php: unparseable month header {label!r}")
    year, month = int(parts.group(2)), MONTHS[parts.group(1).lower()]

    days: dict[int, Day] = {}
    for td in _TD_RE.finditer(table):
        cm = _CLASS_RE.search(td.group(1))
        inner = _clean(td.group(2))
        if not cm or not inner.isdigit():
            continue  # weekday header or blank padding cell
        days[int(inner)] = Day(state=cm.group(1).strip().lower())
    if not days:
        raise FetchError("disponibilita.php: month table has no day cells")
    for rv in _REVEAL_RE.finditer(table):
        d = int(rv.group(1))
        if d in days:
            days[d].details = _DETTAGLI_RE.findall(rv.group(2))
    return Month(year=year, month=month, label=label, days=days)


def parse_offer(fragment: str) -> Offer | None:
    """One <div class="dettagli"> -> Offer, or None if the line isn't understood."""
    maxp = _MAXP_RE.search(fragment)
    icons = len(re.findall(r"fi-torso", fragment))
    if maxp or icons:  # a whole room: "[n. K ]<room name><br/><person icons>"
        cap = int(maxp.group(1)) if maxp else icons
        head = _clean(re.split(r"<br\s*/?>", fragment, maxsplit=1, flags=re.I)[0])
        hm = _ROOM_HEAD_RE.fullmatch(head)
        # [ASSUMPTION] a room line without "n. K" (seen at Tissi) means one room.
        count, name = (int(hm.group(1)), hm.group(2).strip()) if hm else (1, head)
        if cap <= 0 or count <= 0 or not name:
            return None
        return Offer(
            name, count * cap,
            f"{count}x {name} (max {cap} pers.)", f"{count}x {_short(name)} (max {cap})",
        )
    text = _clean(fragment)
    bm = _BEDS_RE.fullmatch(text)
    if not bm:
        return None
    n = int(bm.group("n"))
    name = bm.group("label").strip(" ,.:;-") or "beds"
    beds = f"{n} bed{'' if n == 1 else 's'}"
    return Offer(name, n, f"{name}: {beds}", f"{_short(name)}: {beds}")


def _short(s: str, n: int = 30) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip(" ,.;:") + "…"


def _ranges(days: list[int]) -> str:
    """[7, 8, 9, 12] -> "7-9, 12"."""
    out: list[str] = []
    for d in days:
        if out and d == last + 1:
            out[-1] = f"{out[-1].split('-')[0]}-{d}"
        else:
            out.append(str(d))
        last = d
    return ", ".join(out)


def classify(month: Month, night: dt.date, guests: int) -> CheckResult:
    day = month.days.get(night.day)
    if day is None:
        raise FetchError(f"disponibilita.php: day {night.day} missing from {month.label}")
    if "chiuso" in day.state.split():
        green = [d for d, x in sorted(month.days.items()) if "libero" in x.state.split()]
        hint = _ranges(green) if green else "none (closed season or sold out)"
        return CheckResult(
            Status.FULL,
            f"not available (grey; site shows sold-out and closed alike). "
            f"Green nights in {month.label}: {hint}",
        )
    if "libero" not in day.state.split():
        return CheckResult(Status.UNKNOWN, f"unrecognised day state class={day.state!r}")

    offers, bad = [], 0
    for frag in day.details:
        o = parse_offer(frag)
        if o is None:
            bad += 1
        else:
            offers.append(o)
    total = sum(o.places for o in offers)
    options = [o.line for o in offers]
    summary = "; ".join(o.short for o in offers)
    if total >= guests:
        note = f" (+{bad} unparsed line(s))" if bad else ""
        return CheckResult(Status.AVAILABLE, f"{total} places free: {summary}{note}", options,
                           split=max(o.places for o in offers) < guests)
    if bad or not offers:
        return CheckResult(
            Status.UNKNOWN,
            f"green day but {bad} of {len(day.details)} detail line(s) unparsed; "
            f"parsed {total} places",
            options,
        )
    return CheckResult(
        Status.FULL, f"only {total} place(s) free, need {guests}: {summary}", options
    )


def _fetch_month(fetch: Fetch, url: str, index: int) -> Month:
    # Same URL shape as the page's own "next month" arrow from the previous month.
    resp = fetch("GET", url, params={"prm": index - 1, "chm": 1})
    if resp.status >= 400:
        raise FetchError(f"HTTP {resp.status} from {resp.url}")
    return parse_month(resp.text())


def check(hut: Hut, night: dt.date, guests: int, fetch: Fetch) -> CheckResult:
    url = hut.params.get("url") or hut.booking_url
    if not url:
        raise ValueError(f"{hut.id}: disponibilita_php needs params['url'] or booking_url")
    # Month index relative to January of the (assumed) server year.
    index = (night.year - _today().year) * 12 + night.month
    month = _fetch_month(fetch, url, index)
    if (month.year, month.month) != (night.year, night.month):
        # Server year differs from ours (e.g. New Year's Eve across time zones):
        # correct by the observed offset once, then give up.
        index += (night.year - month.year) * 12 + (night.month - month.month)
        month = _fetch_month(fetch, url, index)
        if (month.year, month.month) != (night.year, night.month):
            raise FetchError(
                f"disponibilita.php: asked for {night:%B %Y}, got {month.label!r}"
            )
    return classify(month, night, guests)
