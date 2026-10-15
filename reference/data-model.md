# Wayfare data model (v0.1)

## Where data lives

Nothing is stored on a Wayfare server. Each user owns their own pages in
their own Claude account:

- **Wayfare Home**: one private page (only the owner can open it, even if
  shared by mistake). It holds the profile, every booking and the list of
  trips with links to their pages.
- **One trip page per trip**, titled like `Lisbon & Porto, Nov 2026`. The
  owner can share it with the people on the trip.

Home page database (rules: everything owner-only):

| Doc                | What it holds |
|--------------------|---------------|
| `index/trips`      | `{trips: [{slug, url, pageTitle, title, dates, startDate, endDate, status, counts, next, bookingIds, sample}]}` |
| `private/profile`  | Travel profile |
| `private/bookings` | `{bookings: [...]}` every booking, with codes and prices |
| `private/fares`    | `{results: [...], checkedAt}` from the last fare check |
| `private/agent`    | `{triggerId}` of the "Wayfare agent" scheduled task |
| `requests/<id>`    | Sync / fare requests started from this page |

Trip page database:

| Path                       | Who reads / writes        | What it holds |
|----------------------------|---------------------------|---------------|
| `trip/data`                | everyone shared / owner   | The trip: items (codes masked, no prices), gaps, alerts with ids, links |
| `private/data`             | owner / owner             | `{items: {<id>: {confirmation, price, manageUrl, ...}}, agent: {triggerId}}` |
| `actions/<alertId>`        | everyone / Editors, owner | `{alertId, fingerprint, status: done|ignored|snoozed, until}` |
| `todos/<id>`               | everyone / Contributors   | `{text, done, at, by}` |
| `suggestions/<alertId>`    | everyone / owner          | Claude's suggestions for an alert (for example stays) |
| `requests/<id>`            | owner / owner             | "Ask Claude" requests and their status |
| `data/users/<id>/calendar` | that person only          | Which items that person added to their calendar |

`scripts/wayfare.py capabilities --page trip|home` prints the exact access
rules for each page. Shared viewers must be signed in to Claude to see data.

An action applies only while the alert's `fingerprint` is unchanged: if the
facts behind an alert change, it comes back.

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
| `manageUrl`    | no       | The "manage booking" link from the email, only if it is `https://` on the sender's own domain. Owner-only |

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
