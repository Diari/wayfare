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
| `private/agent`    | `{triggerId, dailyTriggerId, repo}`: the "Wayfare agent" and "Wayfare daily check" tasks, and where scheduled runs can fetch the plugin |
| `private/status`   | `{results: [...], checkedAt}`: live flight status records (see "Status record") |
| `private/chats`    | `{chats: {"<slug>": {triggerId, url, createdAt}}}`: trip chats made with `/wayfare:trip` |
| `private/weather`  | `{days: [{city, date, hi, lo, code, rain, kind}], places, checkedAt}` from `scripts/weather.py`; `kind` is `forecast` (next 16 days) or `lastYear` |
| `private/changes`  | `{items: [{at, slug, summary}]}`: changes found by background checks, newest 50 |
| `requests/<id>`    | Sync / fare requests started from this page |

Trip page database:

| Path                       | Who reads / writes        | What it holds |
|----------------------------|---------------------------|---------------|
| `trip/data`                | everyone shared / owner   | The trip: items (codes masked, no prices), gaps, alerts with ids, links |
| `private/data`             | owner / owner             | `{items: {<id>: {confirmation, price, manageUrl, ...}}, agent: {triggerId}}` |
| `actions/<alertId>`        | everyone / Editors, owner | `{alertId, fingerprint, status: done|ignored|snoozed, until}` |
| `todos/<id>`               | everyone / Contributors   | `{text, done, at, by}` |
| `suggestions/<alertId>`    | everyone / owner          | Claude's suggestions for an alert (for example stays) |
| `guide/data`               | everyone / owner          | The "Good to know" tab: summary, pack list, local facts, getting around, sources (skills/guide) |
| `data/users/<you>/packing` | only you                  | `{done: [packItemId]}`: your own ticks on the pack list |
| `requests/<id>`            | owner / owner             | "Ask Claude" requests and their status |
| `data/users/<id>/calendar` | that person only          | Which items that person added to their calendar |

`scripts/wayfare.py capabilities --page trip|home` prints the exact access
rules for each page. Shared viewers must be signed in to Claude to see data.

An action applies only while the alert's `fingerprint` is unchanged: if the
facts behind an alert change, it comes back.

Each alert in `trip/data` also has:

- `anchor`: the item id of the card that shows the alert (the last of its
  `itemIds`). Other cards in `itemIds` get a colored border only. A
  `lodging_gap` has no anchor; it shows on its gap card.
- `primary`: the one visible button, `{label, url, itemId?, manage?}`, or
  null. When `manage` is true, the owner's page uses the private
  `manageUrl` of `itemId` instead of `url`. When the alert has `ask` and the
  owner has the agent task, the page shows "Find stays with Claude" instead.
  Everything else goes in the card's menu.

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
  "delayAlertMinutes": 20,
  "fareChecks": false,
  "flights": "free text: seats, airlines, alliances",
  "stays": "free text: hotel style, area, budget",
  "dining": "free text: diet, how far ahead to book"
}
```

`homeAirports` and `homeCity` decide where a trip starts and ends.
`delayAlertMinutes`: a live delay at or above this makes an alert.
`fareChecks`: the daily check looks for lower fares (needs a SearchApi key).

## Manual plans

Plans added in a trip chat use the same booking objects with
`"source": "manual"` and an id that starts with `manual-`. Only these may be
changed or removed from a chat.

## Status record

Written by `scripts/flight_status.py` (Aviationstack) or by hand from a
public flight page. Times are local airport times without offset.

```json
{"bookingId": "flight-TP669-2026-11-06", "flight": "TP 669", "flightDate": "2026-11-06",
 "state": "scheduled | active | landed | cancelled | diverted",
 "depScheduled": "2026-11-06T16:55", "depEstimated": "2026-11-06T17:40", "depActual": null,
 "arrScheduled": "2026-11-06T18:50", "arrEstimated": null, "arrActual": null,
 "depTerminal": "2", "depGate": "D7", "arrTerminal": null, "arrGate": null, "baggage": null,
 "checkedAt": "2026-11-06T13:05:00+00:00", "source": "Aviationstack"}
```

The build uses a record only when it is less than 18 hours old and for the
booked date. It moves the flight to the expected times for all checks (so a
delay shows the dinner or connection it breaks) and shows the booked times
on the page with a live line: status, new times, terminal, gate, bags belt.
Alerts: `flight_delayed` (medium, high at 2 hours or more),
`flight_cancelled` and `flight_diverted` (high).
