"""Cancellation watch targets. Engine params come from inspecting each booking engine;
see STATUS.md. Tracker rows (matched by `aliases`) supply Booked status and phone
(the tracker phone wins over the one here). Nuvolau is watched by hutwatch/nuvolau.py."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .engines.base import Hut

GUESTS = 2

# Booking Suedtirol's API (Fanes, Lavarella, Pederue, Fodara) answers HTTP 403 to requests
# from GitHub's hosted runners (cloud IP ranges) while serving the same honest request from
# an ordinary connection. That is bot protection, so those huts are not queried on GitHub
# Actions (params["blocked_on_ci"]); they still run when hutwatch is run elsewhere.


@dataclass
class BedHut:
    hut: Hut
    aliases: list[str] = field(default_factory=list)


@dataclass
class BedNight:
    night: dt.date            # check-in date (check-out = next day)
    huts: list[BedHut]        # priority order


FANES = BedHut(Hut(
    id="fanes", name="Rifugio Fanes", engine="fanes_family",
    booking_url="https://www.rifugiofanes.com/en/booking",
    params={"property_id": 13308, "source_id": 98, "blocked_on_ci": True, "max_adults": 5, "max_children": 4},
    phone="+39 0474 453001", email="info@rifugiofanes.com"), ["Rifugio Fanes"])

LAVARELLA = BedHut(Hut(
    id="lavarella", name="Rifugio Lavarella", engine="fanes_family",
    booking_url="https://www.lavarella.it/en/book-online",
    params={"property_id": 13004, "source_id": 98, "blocked_on_ci": True, "max_adults": 5, "max_children": 3},
    phone="+39 0474 501094", email="rifugio@lavarella.it"), ["Lavarella"])

PEDERUE = BedHut(Hut(
    id="pederue", name="Berggasthaus Pederü", engine="fanes_family",
    booking_url="https://www.pederue.it/en#Y7D0a11V",
    params={"property_id": 10716, "source_id": 98, "blocked_on_ci": True, "max_adults": 4, "max_children": 3},
    phone="+39 0474 834316", email="info@pederue.it"), ["Pederü", "Pederue"])

FODARA = BedHut(Hut(
    id="fodara_vedla", name="Rifugio Fodara Vedla", engine="fanes_family",
    booking_url="https://www.fodara.it/en#q9ShPDKO",
    params={"property_id": 12869, "source_id": 98, "blocked_on_ci": True, "max_adults": 8, "max_children": 3},
    phone="+39 348 853 7471", email="rifugio@fodara.it"), ["Fodara"])

BIELLA = BedHut(Hut(
    id="biella", name="Rifugio Biella", engine="planyo",
    booking_url="https://www.planyo.com/booking.php?calendar=67368&mode=resource_list&planyo_lang=EN",
    params={"site_id": 67368, "max_ahead_days": 365,
            "rooms": {"224735": ["Cima Nove", 6], "224733": ["Col de Lasta", 4],
                      "224780": ["Croda del Becco", 2], "224728": ["Croda Rossa", 6],
                      "224732": ["Pelmo", 6], "224734": ["Piccola Croda", 7],
                      "224779": ["Sorapis", 8], "224729": ["Tofane", 8]}},
    phone="+39 349 2890550", email="info@rifugiobiella.com"), ["Biella", "Seekofel"])

LAGAZUOI = BedHut(Hut(
    id="lagazuoi", name="Rifugio Lagazuoi", engine="disponibilita_php",
    booking_url="https://rifugiolagazuoi.com/EN/disponibilita.php",
    params={"url": "https://rifugiolagazuoi.com/EN/disponibilita.php"},
    phone="+39 0436 867303", email="info@rifugiolagazuoi.com"), ["Lagazuoi"])

SCOTONI = BedHut(Hut(
    id="scotoni", name="Rifugio Scotoni", engine="bukly",
    booking_url="https://scotoni.bukly.com/booking",
    params={"slug": "scotoni", "hotel_id": 4820},
    phone="+39 0471 847330", email="info@scotoni.it"), ["Scotoni"])

COL_GALLINA = BedHut(Hut(
    id="colgallina", name="Rifugio Col Gallina", engine="bukly",
    booking_url="https://rifugiocolgallina.bukly.com/booking",
    params={"slug": "rifugiocolgallina", "hotel_id": 4729},
    phone="+39 0436 2939", email="info@rifugiocolgallina.com"), ["Col Gallina"])

AVERAU = BedHut(Hut(
    id="averau", name="Rifugio Averau", engine="bukly",
    booking_url="https://rifugioaverau.bukly.com/booking",
    params={"slug": "rifugioaverau", "hotel_id": 3312},
    phone="+39 0436 4660", email="rifugioaverau@gmail.com"), ["Averau"])

SCOIATTOLI = BedHut(Hut(
    id="scoiattoli", name="Rifugio Scoiattoli", engine="scoiattoli_booking",
    booking_url="https://www.rifugioscoiattoli.it/booking/eng/",
    params={"url": "https://www.rifugioscoiattoli.it/booking/"},
    phone="+39 0436 762030", email="info@rifugioscoiattoli.it"), ["Scoiattoli"])

# Not queryable (enquiry form / email / no website) -> change-watched by the page watch:
#   22 Jun: Rifugio Sennes, Ücia dles Muntagnoles
#   23 Jun: Rifugio Cinque Torri, Capanna Alpina
# Rifugio Nuvolau (23 + 24 Jun) is checked by hutwatch/nuvolau.py. See STATUS.md.

NIGHTS: list[BedNight] = [
    BedNight(dt.date(2027, 6, 22), [FANES, LAVARELLA, PEDERUE, FODARA, BIELLA]),
    BedNight(dt.date(2027, 6, 23), [LAGAZUOI, SCOTONI, COL_GALLINA, AVERAU, SCOIATTOLI]),
]
