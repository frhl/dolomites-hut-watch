#!/usr/bin/env python3
"""Make the repo copy of the booking tracker: only what the watches need.

    python3 scripts/sanitize_tracker.py ~/Downloads/AV1-booking-tracker.xlsx

Keeps sheet "Nights", only the columns Night / Plan / Backup / Place / Status / Phone,
and only rows for nights the watches use. Drops every other sheet (flights, key dates),
notes, prices, deposits, booking refs, emails and document metadata. Writes
AV1-booking-tracker.xlsx at the repo root (or the path given as 2nd argument).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hutwatch import beds_config, nuvolau, pagewatch_config, tracker  # noqa: E402

KEEP = ["Night", "Plan / Backup", "Place", "Status", "Phone"]


def watched_nights() -> set[dt.date]:
    nights = {n.night for n in beds_config.NIGHTS} | {n.night for n in nuvolau.NIGHTS}
    nights |= {h.night for h in pagewatch_config.HUTS}
    return nights


def sanitize(src: Path, dst: Path) -> int:
    wb = openpyxl.load_workbook(src, data_only=True)
    ws = wb[tracker.SHEET]
    header_idx, header = None, []
    rows = []
    for values in ws.iter_rows(values_only=True):
        cells = ["" if v is None else v for v in values]
        if header_idx is None:
            names = [str(c).strip() for c in cells]
            if {"Night", "Place", "Status"} <= set(names):
                header_idx = {n: i for i, n in enumerate(names) if n}
                header = [k for k in KEEP if k in header_idx]
            continue
        night = cells[header_idx["Night"]]
        if isinstance(night, dt.datetime):
            night = night.date()
        if not isinstance(night, dt.date) or night not in watched_nights():
            continue
        rows.append([night if k == "Night" else (cells[header_idx[k]] or None) for k in header])
    if header_idx is None:
        raise SystemExit(f"{src}: no Night/Place/Status header in sheet {tracker.SHEET!r}")

    out = openpyxl.Workbook()
    o = out.active
    o.title = tracker.SHEET
    o.append(header)
    for r in rows:
        o.append(r)
    for cell in o["A"][1:]:
        cell.number_format = "yyyy-mm-dd"
    o.column_dimensions["C"].width = 40
    out.properties.creator = "hutwatch"
    out.properties.lastModifiedBy = "hutwatch"
    out.save(dst)
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "AV1-booking-tracker.xlsx"
    n = sanitize(Path(sys.argv[1]).expanduser(), dst)
    print(f"wrote {dst} ({n} rows, columns {', '.join(KEEP)})")
