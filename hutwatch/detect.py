"""Booking-language detection and change diffs for the page watch."""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass

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


# ---------------- Page changes: important or not, in plain words ----------------

# Leftover HTML (tags, "/h2>", entities) - ignored when deciding whether words changed.
_MARKUP = re.compile(r"</?[a-z][a-z0-9]*\b[^<>]{0,80}>|/?\b[a-z][a-z0-9]?>|&[a-z]+;|&#\d+;", re.I)
# Bookings said to be open, without a year ("Prenotazioni aperte", "Book now").
OPEN_NOW = re.compile(
    r"prenotazioni\s+(?:\S+\s+){0,2}?aperte|prenota\s+(?:ora|adesso|subito)|aperte\s+le\s+prenotazioni"
    r"|\bbook(?:ing|ings)?\s+(?:is\s+|are\s+)?(?:now\s+)?open\b|\bbook\s+now\b|\bnow\s+(?:open\s+for\s+)?book"
    r"|reservations?\s+(?:are\s+|is\s+)?(?:now\s+)?open\b"
    r"|buchung(?:en)?\s+(?:\S+\s+){0,2}?m[oö]glich|jetzt\s+buchen",
    re.I,
)
NEXT_SEASON = re.compile(r"prossima\s+stagione|next\s+season|n[aä]chsten?\s+saison|summer\s+2027", re.I)


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", _MARKUP.sub(" ", s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s.casefold()))


def _cut(s: str, n: int = 90) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _word_changes(a: str, b: str, max_ops: int = 3) -> list[str] | None:
    """Short 'what changed' for two versions of a sentence, or None if too different."""
    aw, bw = a.split(), b.split()
    ops = [o for o in difflib.SequenceMatcher(None, aw, bw, autojunk=False).get_opcodes() if o[0] != "equal"]
    if not ops or len(ops) > max_ops:
        return None
    out = []
    for tag, i1, i2, j1, j2 in ops:
        o, n = " ".join(aw[i1:i2]), " ".join(bw[j1:j2])
        out.append(f"«{_cut(o, 60)}» → «{_cut(n, 60)}»" if tag == "replace"
                   else f"removed «{_cut(o, 60)}»" if tag == "delete" else f"added «{_cut(n, 60)}»")
    return out


@dataclass
class Change:
    important: bool
    why: str            # first line of the push, plain words
    details: list[str]  # what they did, a few short lines

    @property
    def label(self) -> str:
        return "IMPORTANT" if self.important else "Not important"

    def message(self, max_lines: int = 5) -> str:
        lines = self.details[:max_lines]
        if len(self.details) > max_lines:
            lines.append(f"(+{len(self.details) - max_lines} more changes)")
        return "\n".join([self.why, *lines])


def explain_change(old: list[str], new: list[str]) -> Change:
    """Classify a change of a page's booking-relevant sentences and describe it.

    IMPORTANT when new text mentions 2027, says bookings are open (or next season), or
    gives a booking date in Dec/Jan/Feb, or when a 'not open yet' / 2027 line disappears.
    Everything else (formatting fixes, other wording) is 'Not important'."""
    removed = [s for s in old if s not in new]
    added = [s for s in new if s not in old]

    # 1. Important?
    reasons = []
    if any(YEAR_2027.search(s) for s in added):
        reasons.append("new text mentions 2027")
    if any(OPEN_NOW.search(s) and not NEGATIVE.search(s) for s in added):
        reasons.append("new text says bookings are open")
    if any(NEXT_SEASON.search(s) and BOOKING_TERMS.search(s) for s in added) and not reasons:
        reasons.append("new text is about booking next season")
    if any(BOOKING_TERMS.search(s) and when_mentions(s) and ANNOUNCE_CONTEXT.search(s) for s in added) \
            and not reasons:
        reasons.append("new text gives a booking date")
    if any(NEGATIVE.search(s) and (BOOKING_TERMS.search(s) or OPEN_TERMS.search(s)) for s in removed):
        reasons.append("a 'not open yet' notice was removed")
    if any(YEAR_2027.search(s) for s in removed) and not any(YEAR_2027.search(s) for s in added) \
            and not reasons:
        reasons.append("text about 2027 was removed")

    # 2. What did they do?
    same_words = ({_norm(s) for s in old} == {_norm(s) for s in new}
                  or _norm(" ".join(old)) == _norm(" ".join(new)))
    details: list[str] = []
    if same_words:
        for r in removed:
            a = next((x for x in added if _norm(x) == _norm(r)), None)
            if a is not None:
                wc = _word_changes(r, a)
                details.append("Fixed: " + ", ".join(wc) if wc else f"Before: «{_cut(r)}»  After: «{_cut(a)}»")
        if not details:
            details.append("Text moved around or split differently.")
        if not reasons:
            return Change(False, "Formatting fix only: the words are the same.", details)
    else:
        left = list(removed)
        for a in added:
            best = max(left, key=lambda r: difflib.SequenceMatcher(None, r, a).ratio(), default=None)
            if best is not None and difflib.SequenceMatcher(None, best, a).ratio() >= 0.5:
                left.remove(best)
                wc = _word_changes(best, a)
                details.append(f"Edited: {', '.join(wc)}\n  Line now: «{_cut(a)}»" if wc
                               else f"Reworded: «{_cut(best)}»\n  Now: «{_cut(a)}»")
            else:
                details.append(f"New: «{_cut(a, 160)}»")
        details += [f"Gone: «{_cut(r, 160)}»" for r in left]

    if reasons:
        why = "Why: " + "; ".join(reasons) + "."
        return Change(True, why, details)
    return Change(False, "Wording changed, nothing about 2027 or bookings opening.", details)
