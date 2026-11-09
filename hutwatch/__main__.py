"""CLI:  python -m hutwatch pages  [--dry-run] [--test-alert]
       python -m hutwatch fast   [--dry-run] [--test-alert] [--only HUT_ID ...]
       python -m hutwatch dense  [--dry-run] [--minutes N]   (Nuvolau 1-min probe, ~1 Feb)
       python -m hutwatch status                              (write the public STATUS.md)

`fast` = cancellation watch + Nuvolau watch. $SCOPE=nuvolau runs only the Nuvolau checks
(the extra 5-min ticks); $SCHEDULE is set when GitHub's own cron started the run, which is
only a backup for the external trigger (see fast.py and pagewatch.run).

With HUTWATCH_PUBLIC_LOG=1 (the workflows: logs of a public repo are public) only
health lines are printed; alert-delivery errors and crashes are written to
state/last_errors.json in the private state repo, and delivery errors don't fail the
run (a red run only after an alert would give the alert away; undelivered alerts are
retried next run instead).
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

from .notify import Notifier
from .redact import install_stream_scrubbers, plog, public, scrub


def _record_errors(mode: str, errors: list[str]) -> None:
    from . import state
    path = state.STATE_DIR / "last_errors.json"
    data = state.load(path)
    log = data.setdefault("entries", [])
    t = state.iso(state.now())
    log.extend({"at": t, "mode": mode, "error": scrub(e)[:2000]} for e in errors)
    data["entries"] = log[-100:]
    state.save(path, data)


def _run(a, notifier: Notifier, test: bool) -> int:
    if a.mode == "pages":
        from . import pagewatch
        return pagewatch.run(notifier, test_alert=test)
    if a.mode == "dense":
        from . import nuvolau
        minutes = a.minutes if a.minutes is not None else (
            float(os.environ["DENSE_MINUTES"]) if os.environ.get("DENSE_MINUTES") else None)
        rc = nuvolau.dense(notifier, minutes=minutes)
        return 1 if notifier.errors else rc
    if a.mode == "status":
        from . import status
        status.write()
        return 0
    from . import fast
    return fast.run(notifier, test_alert=test, only=set(a.only) if a.only else None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hutwatch")
    ap.add_argument("mode", choices=["pages", "fast", "dense", "status"])
    ap.add_argument("--dry-run", action="store_true", help="print alerts instead of sending them")
    ap.add_argument("--test-alert", action="store_true", help="send test alerts first")
    ap.add_argument("--only", nargs="*", help="fast: check only these hut ids")
    ap.add_argument("--minutes", type=float, help="dense: loop this long, ignoring the date window")
    a = ap.parse_args(argv)
    install_stream_scrubbers()
    test = a.test_alert or os.environ.get("TEST_ALERT", "").lower() == "true"
    notifier = Notifier(dry_run=a.dry_run)
    if not public():
        return _run(a, notifier, test)
    try:
        rc = _run(a, notifier, test)
    except Exception:  # noqa: BLE001
        _record_errors(a.mode, list(notifier.errors) + [traceback.format_exc()])
        plog("FAIL: internal error (details in the private state repo)")
        return 1
    if notifier.errors:
        _record_errors(a.mode, list(notifier.errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
