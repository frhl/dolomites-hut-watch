# fanes_family fixtures (Booking Südtirol widget API)

Raw response bodies, byte-for-byte as served, captured 2026-11-08 between 17:43 and 17:48 UTC
(Lavarella: a few minutes later, same day)
from `api.widgets.bookingsuedtirol.com` (server: Google Frontend, `Content-Type: application/json`,
HTTP 200 for all). Every request was a plain GET sent by `hutwatch.http.request` with these headers:

```
User-Agent: hut-booking-watch/1.0 (personal mountain-hut availability monitor; low-frequency, read-only; github.com/frhl/dolomites-hut-watch)
Accept: application/json
Accept-Language: en,it;q=0.8,de;q=0.6
```

No cookies, Referer, Origin or API key: the API needs none. `guests` is the URL-encoded
`JSON.stringify` of a list of rooms, each a list of guest ages: `%5B%5B18%2C18%5D%5D` = `[[18,18]]`
(one room, 2 adults), `%5B%5B18%5D%2C%5B18%5D%5D` = `[[18],[18]]` (two 1-adult units, which is what
matches per-bed dormitory units). Base: `https://api.widgets.bookingsuedtirol.com/v6`.

## Availability calendar (`GET /properties/{id}/availabilities`): what the engine queries

The engine requests exactly these URLs for night 2027-06-22 or 2027-06-23 (window = calendar month,
widened back 14 days only when the night is early in the month).

| fixture | request (GET, base + ...) | state |
|---|---|---|
| `fanes_avail_2027-06_room2.json` | `/properties/13308/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%2C18%5D%5D&sourceId=98` | target 22 Jun **full** (no stay covers it); 23 Jun: `2027-06-24 minimum_stay_not_fulfilled` (**1-night refused**) + `2027-06-25 departure_possible` |
| `fanes_avail_2027-06_split1x2.json` | `/properties/13308/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%5D%2C%5B18%5D%5D&sourceId=98` | 22 Jun full; 20 Jun 1-night bookable |
| `pederue_avail_2027-06_room2.json` | `/properties/10716/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%2C18%5D%5D&sourceId=98` | 22 Jun full |
| `pederue_avail_2027-06_split1x2.json` | `/properties/10716/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%5D%2C%5B18%5D%5D&sourceId=98` | 22 Jun full |
| `fodara_avail_2027-06_room2.json` | `/properties/12869/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%2C18%5D%5D&sourceId=98` | 22 Jun full; **23 Jun available** (1 night, `departure_possible`) |
| `fodara_avail_2027-06_split1x2.json` | `/properties/12869/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%5D%2C%5B18%5D%5D&sourceId=98` | 22 and 23 Jun full |
| `lavarella_avail_2027-06_room2.json` | `/properties/13004/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%2C18%5D%5D&sourceId=98` | June on sale (arrivals 5-16 Jun), 22 Jun full, nothing bookable 17-30 Jun |
| `lavarella_avail_2027-06_split1x2.json` | `/properties/13004/availabilities?from=2027-06-01&to=2027-06-30&guests=%5B%5B18%5D%2C%5B18%5D%5D&sourceId=98` | same picture (arrivals 5-15 Jun) |

### Edited fixture (not a live response)

`fanes_avail_2027-06_room2_EDITED_minstay_only.json` is `fanes_avail_2027-06_room2.json` with one
change: in the `2027-06-23` entry the element `{"departure":"2027-06-25","rule":"departure_possible"}`
(and its leading comma) was deleted, so the night is covered only by a refused 1-night stay. This
state (night free, every stay over it refused by the minimum-stay rule) was not observed live: the
API seems to drop arrival dates that have no bookable departure (e.g. Fanes 16 Jun, free inside
15->17 yet not listed). It exercises the engine's `MIN_STAY` branch.

## Offers (`GET /properties/{id}/offers`): only used to name rooms/prices once available

Params are the widget's own. The fixtures were fetched with a fixed probe `correlationId`; the
engine sends a random 23-character one, as the widget does. `guestCount` = number of rooms + 1
(that is what the widget sends).

| fixture | request (GET, base + ...) | notes |
|---|---|---|
| `fanes_offers_2027-06-22_1night_room2.json` | `/properties/13308/offers?guests=%5B%5B18%2C18%5D%5D&sourceId=98&from=2027-06-22&to=2027-06-23&lang=en&correlationId=hutwatchProbe0000000001&guestCount=2&maxAdults=5&maxChildren=4` | target night, full: all lists empty, `resultId: null` |
| `fanes_offers_2027-06-23_1night_room2_minstay_refused.json` | `/properties/13308/offers?guests=%5B%5B18%2C18%5D%5D&sourceId=98&from=2027-06-23&to=2027-06-24&lang=en&correlationId=hutwatchProbe0000000002&guestCount=2&maxAdults=5&maxChildren=4` | **1-night minimum refused** (night is free). Body identical to the full one above, so offers can't tell them apart |
| `fanes_offers_2027-06-23_2nights_room2.json` | `/properties/13308/offers?guests=%5B%5B18%2C18%5D%5D&sourceId=98&from=2027-06-23&to=2027-06-25&lang=en&correlationId=hutwatchProbe0000000003&guestCount=2&maxAdults=5&maxChildren=4` | available: room 53500 `room_free: 1`, `price_total: 692` |
| `fodara_offers_2027-06-23_1night_room2.json` | `/properties/12869/offers?guests=%5B%5B18%2C18%5D%5D&sourceId=98&from=2027-06-23&to=2027-06-24&lang=en&correlationId=hutwatchProbe0000000004&guestCount=2&maxAdults=8&maxChildren=3` | available: room 67855 (dorm "Lager") `room_free: 1`, `price_total: 238` |

## Room names (`GET /properties/{id}/rooms`)

| fixture | request |
|---|---|
| `fanes_rooms_en.json` | `/properties/13308/rooms?lang=en&sourceId=98` |
| `fodara_rooms_en.json` | `/properties/12869/rooms?lang=en&sourceId=98` |

## Widget configuration (reference only: source of `source_id`, `max_adults`, `max_children`)

| fixture | request | key values |
|---|---|---|
| `fanes_widget.json` | `/widgets?id=8501930f-1806-4a11-bdfe-03a3942aa693` (widget id is in the rifugiofanes.com page source) | `easy_channel_id` 98, `property_id` 13308, `max_adults` 5, `max_children` 4 |
| `pederue_widget.json` | `/widgets?propertyId=10716&type=booking&source=widget` (how the HGV site builder's widget resolves it) | widget `408beb7e-…`, 98, 10716, 4, 3 |
| `fodara_widget.json` | `/widgets?propertyId=12869&type=booking&source=widget` | widget `e2e914d9-…`, 98, 12869, 8, 3 |
| `lavarella_widget.json` | `/widgets?propertyId=13004&type=booking&source=widget` (lavarella.it itself loads the older `widget.bookingsuedtirol.com/widget.js` with `accommodationId: 13004`) | widget `d799973c-…`, 98, 13004, 5, 3 |
