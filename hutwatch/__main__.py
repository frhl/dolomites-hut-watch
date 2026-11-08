"""CLI:  python -m hutwatch pages [--dry-run] [--test-alert]
       python -m hutwatch fast  [--dry-run] [--test-alert] [--only HUT_ID ...]
       python -m hutwatch dense [--dry-run] [--minutes N]   (Nuvolau 1-min probe, ~1 Feb)

`fast` = cancellation watch + Nuvolau watch (reads $SCHEDULE to tell 15-min ticks
from the extra 5-min Nuvolau ticks; empty = manual run = everything).
"""

from __future__ import annotations

import argparse
import os
import sys

from .notify import Notifier


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hutwatch")
    ap.add_argument("mode", choices=["pages", "fast", "dense"])
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending them")
    ap.add_argument("--test-alert", action="store_true", help="send test alerts first")
    ap.add_argument("--only", nargs="*", help="fast: check only these hut ids")
    ap.add_argument("--minutes", type=float, help="dense: loop this long, ignoring the date window")
    a = ap.parse_args(argv)
    from .redact import install_stream_scrubbers
    install_stream_scrubbers()
    test = a.test_alert or os.environ.get("TEST_ALERT", "").lower() == "true"
    notifier = Notifier(dry_run=a.dry_run)
    if a.mode == "pages":
        from . import pagewatch
        return pagewatch.run(notifier, test_alert=test)
    if a.mode == "dense":
        from . import nuvolau
        minutes = a.minutes if a.minutes is not None else (
            float(os.environ["DENSE_MINUTES"]) if os.environ.get("DENSE_MINUTES") else None)
        rc = nuvolau.dense(notifier, minutes=minutes)
        return 1 if notifier.errors else rc
    from . import fast
    return fast.run(notifier, test_alert=test, only=set(a.only) if a.only else None)


if __name__ == "__main__":
    sys.exit(main())
