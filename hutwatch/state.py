"""JSON state files. They hold results and page text, so they live in the PRIVATE repo
frhl/dolomites-hut-watch-state, checked out at ./private (never in the public repo)."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
# HUTWATCH_STATE_DIR lets the Mac launchd job keep its own state outside the repo.
STATE_DIR = (Path(os.environ["HUTWATCH_STATE_DIR"]) if os.environ.get("HUTWATCH_STATE_DIR")
             else ROOT / "private" / "state")
ROME = ZoneInfo("Europe/Rome")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def today_rome() -> dt.date:
    return dt.datetime.now(ROME).date()


def iso(t: dt.datetime | None) -> str | None:
    return t.isoformat() if t else None


def parse(s: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(s) if s else None


def load(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    from .redact import scrub
    text = scrub(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)) + "\n"
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
