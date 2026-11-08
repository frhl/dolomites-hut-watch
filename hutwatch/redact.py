"""Keep secrets and results out of anything public.

- scrub(): removes secret values (ntfy topic, tokens) from text that is printed, stored or posted.
- Public mode (HUTWATCH_PUBLIC_LOG=1, set by the workflows because Actions logs of a public
  repo are public): log() prints nothing; only plog() lines appear, and callers use plog()
  solely for "checked <hut>: ok | FAIL (<reason>)" style lines that do not depend on
  availability. Details stay in the private state repo.
"""

from __future__ import annotations

import os
import re
import sys

SECRET_ENV = ("NTFY_TOPIC", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_TOKEN", "GH_TOKEN")


def public() -> bool:
    return os.environ.get("HUTWATCH_PUBLIC_LOG") == "1"


def _secrets() -> list[str]:
    vals = [os.environ.get(k, "").strip() for k in SECRET_ENV]
    return sorted({v for v in vals if len(v) >= 6}, key=len, reverse=True)


def scrub(text: str) -> str:
    for v in _secrets():
        text = text.replace(v, "<redacted>")
    return text


def log(*args, **kw) -> None:
    """Detailed log line: suppressed in public mode."""
    if not public():
        print(scrub(" ".join(str(a) for a in args)), **kw)


def plog(line: str) -> None:
    """Public-safe line (health only). Also goes to the job summary in public mode."""
    line = scrub(line)
    print(line)
    if public() and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"- {line}\n")


def reason(err: BaseException) -> str:
    """Short, content-free failure reason: 'HTTP 503', 'timeout', 'network error', ..."""
    msg = str(err)
    m = re.match(r"HTTP (\d{3})", msg)
    if m:
        return f"HTTP {m.group(1)}"
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return "timeout"
    if "unclassifiable" in low or "unrecognised" in low or "unknown" in low:
        return "unrecognised response"
    if "urlerror" in low or "name or service" in low or "nodename" in low or "connection" in low:
        return "network error"
    if "json" in low or "parse" in low or "unparseable" in low:
        return "unreadable response"
    return type(err).__name__


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
