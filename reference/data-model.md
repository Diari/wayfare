# Wayfare data model (v0.1)

## Where data lives

All Wayfare data lives in the database of ONE Claude artifact per user, titled
**Wayfare Trips**. Nothing is stored on a Wayfare server. Each user owns their
own copy in their own Claude account.

| Collection / doc   | Who can read                      | What it holds                                            |
|--------------------|-----------------------------------|----------------------------------------------------------|
| `trips/<slug>`     | everyone the page is shared with  | One trip, shared-safe: no prices, codes masked (`••••KM`) |
| `meta/status`      | everyone the page is shared with  | Last update time, counts, `sample: true` for sample data  |
| `private/bookings` | owner only                        | `{bookings: [...]}` full bookings, with codes and prices  |
| `private/profile`  | owner only                        | Travel profile                                            |
| `private/fares`    | owner only                        | `{results: [...], checkedAt}` from the last fare check    |

The page declares these access rules when it is published:

```json
{"db": {"rules": [
  {"path": "", "read": "view", "write": "owner"},
  {"path": "private", "read": "owner", "write": "owner"}
]}, "user": {}}
```

Only the owner (and Claude acting as the owner) writes. Shared viewers must be
signed in to Claude to see data. Viewers never see `private/*`.

## Booking object

Every booking is one JSON object. `scripts/wayfare.py validate` checks them.

Common fields:

| Field          | Required | Notes |
|----------------|----------|-------|
| `id`           | yes      | Stable id, see "Ids" below |
| `type`         | yes      | `flight`, `train`, `transfer`, `hotel`, `dining`, `other` |
| `status`       | no       | `confirmed` (default), `changed`, `cancelled` |
| `provider`     | no       | Airline, hotel brand, rail company, "OpenTable" |
| `bookedVia`    | no       | Where it was booked: "klm.com", "Booking.com" |
| `confirmation` | no       | Booking code / PNR. Owner-only. Never put it anywhere else |
| `travelers`    | no       | Number of people on the booking (default 1) |
| `price`        | no       | `{"amount": 412.0, "currency": "EUR"}` total for the booking |
| `refundable`   | no       | `true`, `false`, or leave out if unknown |

`flight`: `carrier` (IATA, "KL"), `flightNumber` ("1734"), `from` and `to`
(3-letter IATA airport codes), `fromCity`, `toCity`, `depart`, `arrive`, `cabin`.
One booking object per flight leg. Two legs on one ticket share the same
`confirmation`.

`train` / `transfer`: `name` ("ICE 145"), `from`, `to` (station names),
`fromCity`, `toCity`, `depart`, `arrive`.

`hotel`: `name`, `city`, `checkIn`, `checkOut` (`YYYY-MM-DD`), optional
`latestCheckIn` (`HH:MM` local) and `checkInFrom` (`HH:MM`).

`dining` / `other`: `name`, `city`, `start` (and optional `end`), `partySize`.

### Times

`depart`, `arrive`, `start` and `end` are ISO 8601 **local wall-clock time
with the UTC offset of that place on that date**:
`2026-11-06T16:55:00+01:00` (Amsterdam in November),
`2026-11-06T18:50:00+00:00` (Lisbon in November). Emails show local times;
add the correct offset for the city and date (summer time matters).
A time without an offset is rejected.

### Schedule changes and cancellations

- Schedule change email: write the booking again with the new times. The
  merge step keeps the old times in `previous` and sets `status: "changed"`.
  If the email shows both old and new times, you may also set
  `previous: {"depart": ..., "arrive": ...}` yourself.
- Cancellation email: write the booking with `status: "cancelled"` and the
  same `confirmation`.

### Ids

Make ids from facts in the booking, so the same booking always gets the same
id:

- flight: `flight-<carrier><number>-<departure date>` → `flight-KL1734-2026-11-12`
- train: `train-<from city>-<to city>-<date>` → `train-lisbon-porto-2026-11-08`
- hotel: `hotel-<short name>-<check-in date>` → `hotel-spreeblick-2026-12-04`
- dining: `dining-<short name>-<date>` → `dining-taberna-azul-2026-11-06`

Lowercase, letters, digits and `-` only.

## Profile object

```json
{
  "homeAirports": ["AMS"],
  "homeCity": "Amsterdam",
  "currency": "EUR",
  "minConnectionMinutes": 75,
  "arrivalToDinnerMinutes": 150,
  "fareDropMinimum": 25,
  "flights": "free text: seats, airlines, alliances",
  "stays": "free text: hotel style, area, budget",
  "dining": "free text: diet, how far ahead to book"
}
```

`homeAirports` and `homeCity` decide where a trip starts and ends.
