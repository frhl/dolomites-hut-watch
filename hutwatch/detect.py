"""Booking-language detection and change diffs for the page watch."""

from __future__ import annotations

import difflib
import hashlib
import re

# "2027" as a year: not part of a longer number and not an ISO timestamp (2027-01-15T...).
YEAR_2027 = re.compile(r"(?<!\d)2027(?!\d|-\d)")

# Booking / opening language (Italian + English). Matched case-insensitively as prefixes.
OPEN_TERMS = re.compile(
    r"prenot|apert|apriam|riapr|stagion|giugno|\bbook|\bopen|season|reserv|disponib|availab",
    re.I,
)

# Sentences that talk about 2027 bookings but say they are NOT open yet.
NEGATIVE = re.compile(
    r"\bnon\s+(?:\S+\s+){0,3}?ancora\b"      # non ancora / non sono ancora / non è ancora ...
    r"|\bnon\s+abbiamo\s+(?:ancora\s+)?iniziato"
    r"|\bnot\s+(?:\S+\s+){0,2}?yet\b"        # not yet / not open yet / not available yet
    r"|\bnot\s+(?:open|available|bookable)"
    r"|\bnon\s+(?:è|e'|sono)?\s*(?:disponibil|prenotabil|apert)"
    r"|\bprossimamente\b|\bcoming\s+soon\b|\ba\s+breve\b",
    re.I,
)

# Booking-relevant sentences for change detection.
RELEVANT = re.compile(r"prenot|apert|chius|stagion|season|saison|reserv|2026|2027|\bbook|\bopen|\bclos",
                      re.I)


def open_matches(sentences: list[str]) -> list[str]:
    """Sentences announcing 2027 bookings/opening, excluding negative ones."""
    return [
        s for s in sentences
        if YEAR_2027.search(s) and OPEN_TERMS.search(s) and not NEGATIVE.search(s)
    ]


def relevant_sentences(sentences: list[str]) -> list[str]:
    return [s for s in sentences if RELEVANT.search(s)]


def digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def diff(old: list[str], new: list[str], max_chars: int = 40_000) -> str:
    out = "\n".join(difflib.unified_diff(old, new, "before", "after", lineterm="", n=1))
    if len(out) > max_chars:
        out = out[:max_chars] + "\n... (diff truncated)"
    return out


# ---------------- Nuvolau: announcement of the 2027 booking opening ----------------

BOOKING_TERMS = re.compile(r"prenot|\bbook|reserv|buchung|buchen", re.I)
# 2027, or the months an opening could be announced for (2026 bookings opened in stages from 1 Feb).
ANNOUNCE_CONTEXT = re.compile(r"(?<!\d)2027(?!\d|-\d)|gennaio|january|j[aä]nner|januar|dicembre|december|"
                              r"dezember|febbraio|february|februar", re.I)
_MONTHS = r"(?:gennaio|january|j[aä]nner|januar|febbraio|february|februar|dicembre|december|dezember)"
_WHEN = [
    re.compile(rf"\b\d{{1,2}}(?:°|º|st|nd|rd|th)?\s+(?:di\s+)?{_MONTHS}(?:\s+20\d\d)?", re.I),
    re.compile(rf"\b{_MONTHS}\s+\d{{1,2}}(?!\d)(?:st|nd|rd|th)?(?:,?\s+20\d\d)?", re.I),
    re.compile(r"\b\d{1,2}[./]\d{1,2}[./](?:20)?\d\d\b"),
    re.compile(r"\b(?:ore|alle|alle ore|h|at|um)\s*\d{1,2}(?:[:.]\d{2})?(?!\d)\b", re.I),
    re.compile(r"\b\d{1,2}[:.]\d{2}\s*(?:am|pm|uhr)?\b", re.I),
    re.compile(r"\b\d{1,2}\s*(?:am|pm)\b", re.I),
]


def when_mentions(sentence: str) -> list[str]:
    """Dates / times mentioned in a sentence, e.g. ['15 gennaio 2027', 'ore 9:00']."""
    out: list[str] = []
    for rx in _WHEN:
        for m in rx.finditer(sentence):
            s = m.group(0).strip()
            if s not in out and not any(s in o for o in out):
                out.append(s)
    return out


def announcement_matches(sentences: list[str]) -> list[str]:
    """Sentences about booking that mention 2027 or Dec/Jan. Negative phrasing ("not open
    yet") is dropped unless the sentence also gives a date or time ("not open yet; opens
    15 January at 9:00" is exactly what we want)."""
    def hit(s: str) -> bool:
        return bool(BOOKING_TERMS.search(s) and ANNOUNCE_CONTEXT.search(s)
                    and (not NEGATIVE.search(s) or when_mentions(s)))

    out = [s for s in sentences if hit(s)]
    # Announcements are often split: "Prenotazioni 2027 a breve. Data: 10 gennaio ore 9."
    for a, b in zip(sentences, sentences[1:]):
        if a not in out and b not in out and when_mentions(a + " " + b) and hit(a + " " + b):
            out.append(f"{a} {b}")
    return out
