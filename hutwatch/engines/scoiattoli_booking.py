"""Engine for Rifugio Scoiattoli's own booking page (rifugioscoiattoli.it/booking/).

Observed 2026-11-08 (custom PHP script, no third-party engine, no JSON API):

- The booking page is a GET form (``action=invia``, ``arrivo``/``partenza`` date
  pickers that also submit ``arrivo_insert``/``partenza_insert`` as YYYY-MM-DD,
  ``nadulti``, ``nbambini_3_12``). Its answer is server-rendered HTML. The server's
  own "move your booking" links use only
  ``?action=invia&arrivo_insert=..&partenza_insert=..&nadulti=..&nbambini_3_12=0&nbambini_0_2=0``,
  and that request returned a body byte-identical to the full form submission, so
  the engine sends exactly that. This step creates nothing: it only lists free
  beds. Choosing beds and entering personal data are later steps the engine never
  touches.
- Every answer echoes the request in ``<div id='riepilogo-step2'>``:
  ``<b>Arrivo:</b> 23/06/2027 ... <b>Partenza:</b> 24/06/2027 ... <b>N. Adulti:</b> 2``.
  The engine checks this echo and raises FetchError if it is missing or different.
- Answers seen:
    "Non ci sono posti disponibili per le date selezionate"  -> FULL. It may add
        "Ci sono posti disponibili spostando la prenotazione: Arrivo il <b>dd/mm/yyyy</b>"
        alternatives, and always offers a waiting list ("lista di attesa").
    "Hai selezionato delle date non corrette!"  -> CLOSED (seen for 5 May 2027, which
        is outside the seasons the date picker allows: 1 Dec 2026-28 Mar 2027 and
        14 Jun-2 Oct 2027 as of 2026-11-08).
    a second-step form (``action=invia-step2``) with one <label> per free unit  -> per unit:
        dorm ("Camerata 9"): <select class='sel_camerata'> with options 0..N, N = free beds;
        private room: <input class='chk_id_camera' data-letti=K> (from the page's own
            JS; no room was offered on any night checked, so this markup is unverified).
    Free places = sum of dorm N + room K. AVAILABLE if >= guests, else FULL. A room
    bigger than the party is still bookable (the site charges 15 EUR per empty bed).
- Minimum stay: none observed. A 1-night New Year's Eve query was answered with a
  plain "no places" plus other 1-night dates, not a min-stay refusal, so the engine
  never returns MIN_STAY. Any other message is reported as UNKNOWN.
- The messages parsed are the Italian ones: point ``url`` at the Italian page
  (``/booking/``), not ``/booking/eng/`` or ``/booking/ted/``.

hut.params:
    url  (str, optional)  booking page; defaults to hut.booking_url.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass

from hutwatch.engines.base import CheckResult, Hut, Status
from hutwatch.http import Fetch, FetchError

_ECHO_RE = re.compile(
    r"<b>\s*Arrivo:\s*</b>\s*(\d{2}/\d{2}/\d{4}).*?"
    r"<b>\s*Partenza:\s*</b>\s*(\d{2}/\d{2}/\d{4}).*?"
    r"<b>\s*N\.\s*Adulti:\s*</b>\s*(\d+)",
    re.S | re.I,
)
_FULL_RE = re.compile(r"Non ci sono posti disponibili", re.I)
_CLOSED_RE = re.compile(r"date non corrette", re.I)
_WAITLIST_RE = re.compile(r"lista di attesa", re.I)
_ALT_RE = re.compile(r"Arrivo il\s*<b>\s*(\d{2}/\d{2}/\d{4})\s*</b>", re.I)
_STEP2_RE = re.compile(r"""name=["']action["']\s+value=["']invia-step2["']""", re.I)
_FORM_RE = re.compile(r"<form\b.*?</form>", re.S | re.I)
_LABEL_RE = re.compile(r"<label\b[^>]*>(.*?)</label>", re.S | re.I)
_NAME_RE = re.compile(r"<p>\s*<b>(.*?)</b>\s*</p>", re.S | re.I)
_PRICE_RE = re.compile(r"<br\s*/?>\s*<b>([^<]*?)</b>\s*</p>", re.S | re.I)
_SELECT_RE = re.compile(
    r"""<select\b[^>]*\bclass=["'][^"']*\bsel_camerata\b[^>]*>(.*?)</select>""", re.S | re.I
)
_OPTION_RE = re.compile(r"""<option\b[^>]*\bvalue=["'](\d+)["']""", re.I)
_ROOM_RE = re.compile(r"""<input\b[^>]*\bchk_id_camera\b[^>]*>""", re.I)
_LETTI_RE = re.compile(r"""\bdata-letti=["']?(\d+)""", re.I)
_BODY_P_RE = re.compile(r"<p>(.*?)</p>", re.S | re.I)


def _clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def build_params(night: dt.date, guests: int) -> dict[str, str | int]:
    """Query string for one night (same shape as the site's own alternative-date links)."""
    return {
        "action": "invia",
        "arrivo_insert": night.isoformat(),
        "partenza_insert": (night + dt.timedelta(days=1)).isoformat(),
        "nadulti": guests,
        "nbambini_3_12": 0,
        "nbambini_0_2": 0,
    }


@dataclass
class Unit:
    name: str
    kind: str      # "dorm" or "room"
    places: int    # free beds (dorm) or room capacity (room)
    price: str

    @property
    def line(self) -> str:
        what = f"{self.places} bed{'' if self.places == 1 else 's'}"
        what = f"{what} free" if self.kind == "dorm" else f"room for {self.places}"
        return f"{self.name}: {what}" + (f" ({self.price})" if self.price else "")


def parse_units(text: str) -> tuple[list[Unit], int]:
    """Second-step form -> (free units, number of <label>s that were not understood)."""
    form = _FORM_RE.search(text)
    units, bad = [], 0
    for lab in _LABEL_RE.finditer(form.group(0) if form else ""):
        body = lab.group(1)
        nm = _NAME_RE.search(body)
        name = _clean(nm.group(1)) if nm else "?"
        pm = _PRICE_RE.search(body)
        price = _clean(pm.group(1)) if pm else ""
        sel = _SELECT_RE.search(body)
        room = _ROOM_RE.search(body)
        if sel:
            values = [int(v) for v in _OPTION_RE.findall(sel.group(1))]
            if not values:
                bad += 1
                continue
            if max(values) > 0:
                units.append(Unit(name, "dorm", max(values), price))
        elif room:
            lm = _LETTI_RE.search(room.group(0))
            if not lm or int(lm.group(1)) <= 0:
                bad += 1
                continue
            units.append(Unit(name, "room", int(lm.group(1)), price))
        else:
            bad += 1
    return units, bad


def classify(text: str, night: dt.date, guests: int) -> CheckResult:
    echo = _ECHO_RE.search(text)
    if not echo:
        raise FetchError("scoiattoli_booking: no Arrivo/Partenza/N. Adulti summary in response")
    want = (night.strftime("%d/%m/%Y"), (night + dt.timedelta(days=1)).strftime("%d/%m/%Y"),
            str(guests))
    if echo.groups() != want:
        raise FetchError(f"scoiattoli_booking: asked for {want}, site answered for {echo.groups()}")

    if _CLOSED_RE.search(text):
        return CheckResult(
            Status.CLOSED,
            "site: 'Hai selezionato delle date non corrette!' (night outside the bookable season)",
        )
    if _FULL_RE.search(text):
        alts = _ALT_RE.findall(text)
        if alts:
            hint = "; site suggests other 1-night arrivals: " + ", ".join(a[:5] for a in alts)
        else:
            hint = "; no nearby dates offered"
        wait = ", waiting list offered" if _WAITLIST_RE.search(text) else ""
        return CheckResult(Status.FULL, f"no places for {guests}{hint}{wait}")
    if _STEP2_RE.search(text):
        units, bad = parse_units(text)
        total = sum(u.places for u in units)
        options = [u.line for u in units]
        summary = "; ".join(options)
        if total >= guests:
            note = f" (+{bad} unparsed unit(s))" if bad else ""
            return CheckResult(Status.AVAILABLE, f"{total} places free: {summary}{note}", options,
                               split=max(u.places for u in units) < guests)
        if bad:
            return CheckResult(
                Status.UNKNOWN, f"{bad} unit(s) unparsed; parsed {total} place(s)", options
            )
        return CheckResult(
            Status.FULL, f"only {total} place(s) free, need {guests}: {summary or 'none'}", options
        )
    # The echo is there but the message is new: report it verbatim-ish.
    after = text[echo.end():]
    msg = next((c for c in (_clean(p) for p in _BODY_P_RE.findall(after)) if c), "")
    return CheckResult(Status.UNKNOWN, f"unrecognised answer: {msg[:120]!r}")


def check(hut: Hut, night: dt.date, guests: int, fetch: Fetch) -> CheckResult:
    url = hut.params.get("url") or hut.booking_url
    if not url:
        raise ValueError(f"{hut.id}: scoiattoli_booking needs params['url'] or booking_url")
    resp = fetch("GET", url, params=build_params(night, guests))
    if resp.status >= 400:
        raise FetchError(f"HTTP {resp.status} from {resp.url}")
    return classify(resp.text(), night, guests)
