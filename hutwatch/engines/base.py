"""Shared types for availability checkers (one module per booking engine).

Every engine module exposes:

    def check(hut: Hut, night: datetime.date, guests: int, fetch: Fetch) -> CheckResult

- `night` is the check-in date; check-out is night + 1 day.
- `fetch` has the signature of hutwatch.http.request (tests pass a fake).
- Ask the engine for exactly `guests` people for that one night. If the engine
  refuses a 1-night stay, query a longer window and read the per-night result
  for `night`; return MIN_STAY only if no per-night answer can be obtained.
- Raise hutwatch.http.FetchError (or let any exception escape) on failure; the
  runner counts it toward the consecutive-failure alert.
- Read-only: never create carts, holds, reservations or submit enquiry forms.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Any


class Status(str, enum.Enum):
    AVAILABLE = "available"  # >= guests beds bookable for the night (any room type)
    FULL = "full"            # engine answered: not enough beds for guests
    MIN_STAY = "min_stay"    # engine refused because of a minimum-stay rule, no per-night info
    CLOSED = "closed"        # hut closed / night not sellable at all
    UNKNOWN = "unknown"      # engine answered but the answer could not be classified


@dataclass
class Hut:
    id: str                       # slug, e.g. "fanes"
    name: str                     # display name, e.g. "Rifugio Fanes"
    engine: str                   # module name in hutwatch.engines
    booking_url: str              # page the user taps to open
    params: dict[str, Any] = field(default_factory=dict)  # engine-specific (property id, host...)
    phone: str | None = None
    email: str | None = None


@dataclass
class CheckResult:
    status: Status
    detail: str = ""              # one-line human summary, e.g. "4 dorm beds, 1 double room"
    options: list[str] = field(default_factory=list)  # optional per-room-type lines
    split: bool = False           # AVAILABLE only because beds in different rooms/units add up


def nights_between(start: dt.date, end: dt.date) -> list[dt.date]:
    """Check-in dates from start (inclusive) to end (exclusive)."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days)]
