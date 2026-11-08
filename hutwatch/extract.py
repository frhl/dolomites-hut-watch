"""HTML -> visible text blocks -> sentences. Stdlib only."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "object"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "button", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "label", "legend", "li", "main", "nav", "ol", "option", "p", "pre",
    "section", "select", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "title",
    "tr", "ul",
}
# Markup that only appears when the CAI portal renders its booking calendar for a hut.
WIDGET_ATTRS = ("data-available", "data-calendar-form", "data-reservation-modal", "data-shelter-data")


@dataclass
class Extracted:
    text: str                                   # whole page, whitespace-normalised
    sentences: list[str]                        # ordered, de-duplicated
    widget_markers: list[str] = field(default_factory=list)


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip: list[str] = []
        self.markers: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip.append(tag)
            return
        if self.skip:
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        a = dict(attrs)
        for name in WIDGET_ATTRS:
            if name in a:
                val = (a.get(name) or "").strip()
                self.markers.append(f"{name}={val[:200]}" if val else name)
        if "calendar" in (a.get("class") or "").split():
            self.markers.append(f"<{tag} class=calendar>")

    def handle_startendtag(self, tag, attrs):
        if tag not in SKIP_TAGS:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[^\s\d])")


def extract(html: str) -> Extracted:
    p = _Parser()
    p.feed(html)
    p.close()
    raw = "".join(p.parts)
    blocks = [re.sub(r"\s+", " ", b).strip() for b in raw.split("\n")]
    blocks = [b for b in blocks if b]
    sentences: list[str] = []
    seen: set[str] = set()
    for b in blocks:
        for s in _SENT_SPLIT.split(b):
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                sentences.append(s)
    text = re.sub(r"\s+", " ", " ".join(blocks)).strip()
    markers = list(dict.fromkeys(p.markers))
    return Extracted(text=text, sentences=sentences, widget_markers=markers)
