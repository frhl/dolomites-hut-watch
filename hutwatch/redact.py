"""Remove secret values from anything that is printed, stored or posted.

GitHub Actions already masks secrets in logs; this is a second layer that also covers
issue bodies, committed state and the Mac job's log file."""

from __future__ import annotations

import os
import sys

SECRET_ENV = ("NTFY_TOPIC", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "GH_TOKEN")


def _secrets() -> list[str]:
    vals = [os.environ.get(k, "").strip() for k in SECRET_ENV]
    return sorted({v for v in vals if len(v) >= 6}, key=len, reverse=True)


def scrub(text: str) -> str:
    for v in _secrets():
        text = text.replace(v, "<redacted>")
    return text


def log(*args, **kw) -> None:
    print(scrub(" ".join(str(a) for a in args)), **kw)


class ScrubList(list):
    """list whose appended strings are scrubbed (Notifier.errors)."""

    def append(self, item) -> None:  # type: ignore[override]
        super().append(scrub(str(item)))


class ScrubStream:
    """Wraps sys.stdout/sys.stderr so stray prints and tracebacks are scrubbed too."""

    def __init__(self, stream):
        self._s = stream

    def write(self, s):
        return self._s.write(scrub(s))

    def __getattr__(self, name):
        return getattr(self._s, name)


def install_stream_scrubbers() -> None:
    if not isinstance(sys.stdout, ScrubStream):
        sys.stdout = ScrubStream(sys.stdout)
    if not isinstance(sys.stderr, ScrubStream):
        sys.stderr = ScrubStream(sys.stderr)
