"""Read the user's AV1 booking tracker (sheet "Nights").

Expected header row (found by scanning, not by position): Night, Place, Status, Phone, ...
"""

from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "AV1-booking-tracker.xlsx"
SHEET = "Nights"


@dataclass
class Row:
    night: dt.date
    place: str
    status: str
    phone: str | None
    email: str | None

    @property
    def booked(self) -> bool:
        return self.status.strip().casefold().startswith("booked")


def norm(s: str) -> str:
    """Lowercase, strip accents and non-alphanumerics: 'Berggasthaus Pederü' -> 'berggasthauspederu'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def load(path: Path | str = DEFAULT_PATH) -> list[Row]:
    """Return tracker rows. Raises on a missing file or unexpected layout."""
    import openpyxl  # imported lazily so the page watch doesn't need it for tests

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[SHEET]
    header: dict[str, int] | None = None
    rows: list[Row] = []
    for values in ws.iter_rows(values_only=True):
        cells = ["" if v is None else v for v in values]
        if header is None:
            names = [str(c).strip().casefold() for c in cells]
            if "night" in names and "place" in names and "status" in names:
                header = {n: i for i, n in enumerate(names) if n}
            continue
        night = cells[header["night"]] if header["night"] < len(cells) else ""
        if isinstance(night, dt.datetime):
            night = night.date()
        if not isinstance(night, dt.date):
            continue
        get = lambda k: (str(cells[header[k]]).strip() or None) if k in header and header[k] < len(cells) else None
        rows.append(Row(night=night, place=get("place") or "", status=get("status") or "",
                        phone=get("phone"), email=get("email")))
    wb.close()
    if header is None:
        raise ValueError(f"{path}: no header row with Night/Place/Status in sheet {SHEET!r}")
    return rows


def load_or_warn(path: Path | str = DEFAULT_PATH) -> list[Row] | None:
    try:
        return load(path)
    except Exception as e:  # missing file, bad layout: keep watching, but say so loudly
        print(f"WARNING: could not read tracker {path}: {e}", file=sys.stderr)
        return None


def find(rows: list[Row], night: dt.date, aliases: list[str]) -> Row | None:
    keys = [norm(a) for a in aliases]
    for r in rows:
        if r.night == night and any(k and k in norm(r.place) for k in keys):
            return r
    return None


def night_booked(rows: list[Row], night: dt.date) -> Row | None:
    """The first row for this night marked Booked, if any (any hut/hotel counts)."""
    for r in rows:
        if r.night == night and r.booked:
            return r
    return None
