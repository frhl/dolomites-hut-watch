"""Page watch (slow, every 4 h): 28 June 2027 huts + change-watch fallbacks."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

STOP_AFTER = dt.date(2027, 6, 28)  # nothing runs after this date (Europe/Rome)


@dataclass
class WatchHut:
    id: str
    name: str            # short name used in issue titles
    night: dt.date
    role: str            # "Preferred" / "Fallback"
    aliases: list[str]   # names to match in the tracker
    email_to: str | None = None
    open_detection: bool = True   # look for "2027 + booking language" (OPEN alerts)


@dataclass
class Page:
    id: str
    hut: str             # WatchHut.id
    label: str           # "CAI booking portal" / "hut website"
    url: str


NIGHT_28 = dt.date(2027, 6, 28)
NIGHT_22 = dt.date(2027, 6, 22)
NIGHT_23 = dt.date(2027, 6, 23)

HUTS: list[WatchHut] = [
    WatchHut("pian-de-fontana", "Pian de Fontana", NIGHT_28, "Preferred",
             ["Pian de Fontana"], email_to="piandefontana@livecom.it"),
    WatchHut("pramperet", "Pramperet", NIGHT_28, "Fallback",
             ["Pramperet", "Sommariva"], email_to="info@rifugiosommarivaalpramperet.it"),
    # Cancellation-watch huts with no queryable booking engine: change detection only.
    WatchHut("muntagnoles", "Muntagnoles", NIGHT_22, "Backup", ["Muntagnoles"], open_detection=False),
    WatchHut("sennes", "Sennes", NIGHT_22, "Backup", ["Sennes"], open_detection=False),
    WatchHut("cinque-torri", "Cinque Torri", NIGHT_23, "Backup", ["Cinque Torri", "5 Torri"],
             open_detection=False),  # its banner already says "2027" + booking words
    WatchHut("capanna-alpina", "Capanna Alpina", NIGHT_23, "Backup", ["Capanna Alpina"],
             open_detection=False),
]

PAGES: list[Page] = [
    Page("pian-de-fontana-cai", "pian-de-fontana", "CAI booking portal",
         "https://www.prenotarifugi.cai.it/dettaglio/?id=5942"),
    Page("pian-de-fontana-site", "pian-de-fontana", "hut website", "http://www.piandefontana.it/"),
    Page("pramperet-cai", "pramperet", "CAI booking portal",
         "https://www.prenotarifugi.cai.it/dettaglio/?id=5925"),
    Page("pramperet-site", "pramperet", "hut website", "https://www.rifugiosommarivaalpramperet.it/"),
    Page("muntagnoles-info", "muntagnoles", "info & reservations page (enquiry form only)",
         "https://www.muntagnoles.com/index.php/en/info-reservations-en"),
    Page("sennes-home", "sennes", "hut website (season dates)", "https://www.sennes.com/"),
    Page("sennes-contact", "sennes", "contact/enquiry page", "https://www.sennes.com/en/contact/index.php"),
    Page("cinque-torri-rooms", "cinque-torri", "rooms/booking page (email only)",
         "https://www.rifugio5torri.it/rooms.html"),
    Page("cinque-torri-home", "cinque-torri", "hut website", "https://www.rifugio5torri.it/"),
    Page("capanna-alpina-info", "capanna-alpina", "Alta Badia tourism listing (no own website)",
         "https://www.altabadia.org/en/info/restaurants/detail/gastronomy/restaurant-capanna-alpina"),
]

EMAIL_SUBJECT = "Prenotazione per il 28 giugno 2027"
# No name in the repo: the sign-off is added by hand (issues are public if the repo is).
EMAIL_BODY = """Buongiorno,
vorrei prenotare per 2 persone per la notte di lunedì 28 giugno 2027, con mezza pensione (cena e colazione). Stiamo percorrendo l'Alta Via 1 e arriveremo da Passo Duran.
Potete confermarmi che il rifugio sarà aperto in quella data e se c'è posto? Se serve una caparra, mi indicate come pagarla?
Grazie mille,
[nome]"""


def hut(hut_id: str) -> WatchHut:
    return next(h for h in HUTS if h.id == hut_id)
