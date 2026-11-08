"""Minimal, polite HTTP client (stdlib only).

Rules enforced here for every request the project makes:
- honest User-Agent naming the project (never a browser string)
- 20 s timeout
- no retries: a failed request is reported to the caller, who counts it as a failure
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

USER_AGENT = (
    "hut-booking-watch/1.0 (personal mountain-hut availability monitor; "
    "low-frequency, read-only; github.com/frhl/dolomites-hut-watch)"
)
TIMEOUT_S = 20
MAX_BYTES = 5_000_000


class FetchError(Exception):
    """Network error, timeout, HTTP status >= 400, or unparseable response."""


@dataclass
class Response:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes
    _text: str | None = field(default=None, repr=False)

    @property
    def content_type(self) -> str:
        return self.headers.get("Content-Type", "") or ""

    def text(self) -> str:
        if self._text is None:
            self._text = decode_body(self.body, self.content_type)
        return self._text

    def json(self) -> Any:
        try:
            return json.loads(self.text())
        except ValueError as e:
            raise FetchError(f"invalid JSON from {self.url}: {e}") from e


def decode_body(body: bytes, content_type: str = "") -> str:
    """Decode using the declared charset, then <meta charset>, then utf-8, then cp1252.

    Some hut sites declare nothing (or utf-8) but serve cp1252 bytes, so a strict
    decode failure falls through to the next candidate.
    """
    candidates: list[str] = []
    m = re.search(r"charset=([\w-]+)", content_type, re.I)
    if m:
        candidates.append(m.group(1))
    mm = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", body[:4096], re.I)
    if mm:
        candidates.append(mm.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "cp1252"]
    for enc in candidates:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    json_body: Any = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = TIMEOUT_S,
) -> Response:
    """Single HTTP request. Raises FetchError on any failure. Never retries."""
    if params:
        sep = "&" if urllib.parse.urlparse(url).query else "?"
        url = url + sep + urllib.parse.urlencode(params, doseq=True)
    hdrs = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.5",
        "Accept-Language": "en,it;q=0.8,de;q=0.6",
    }
    if headers:
        hdrs.update(headers)
        hdrs["User-Agent"] = USER_AGENT  # never overridable
    payload: bytes | None = None
    if json_body is not None:
        payload = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    elif data is not None:
        payload = urllib.parse.urlencode(data, doseq=True).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=payload, headers=hdrs, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(MAX_BYTES)
            return Response(status=r.status, url=r.geturl(), headers=dict(r.headers), body=body)
    except urllib.error.HTTPError as e:
        try:
            snippet = " ".join(e.read(300).decode("utf-8", "replace").split())[:160]
        except Exception:  # noqa: BLE001
            snippet = ""
        raise FetchError(f"HTTP {e.code} from {url}" + (f" [{snippet}]" if snippet else "")) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(f"{type(e).__name__} fetching {url}: {e}") from e


# Engines receive a callable with this signature so tests can inject fixtures.
Fetch = Callable[..., Response]
