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
| `private/plans`    | `{plans: [...]}`: trips not booked yet (see "Plan object") |
| `private/planprices` | `{results: {<planId>: record}}`: the last plan search and its price history |
| `index/plans`      | `{plans: [{id, title, dates, startDate, status, url, currency, total, totalLowest, checkedAt, alerts, travellers, trend}]}`: plan cards on Home |

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
| `freeCancelUntil` | no    | Stays: the last moment to cancel for free (ISO with offset, or `YYYY-MM-DD`) |
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
  "stayDropMinimum": 30,
  "flights": "free text: seats, airlines, alliances",
  "stays": "free text: hotel style, area, budget",
  "dining": "free text: diet, how far ahead to book"
}
```

`homeAirports` and `homeCity` decide where a trip starts and ends.
`delayAlertMinutes`: a live delay at or above this makes an alert.
`fareChecks`: the daily check looks for lower fares on flights and lower
prices with free cancellation on refundable stays (needs a SearchApi key).
`stayDropMinimum`: the smallest drop in the total price of a stay worth an
alert.

## Stay price record

Written by `scripts/stay_check.py` into the same results list as the fare
records (`private/fares` on Claude, `fares.json` on Codex):

```json
{"bookingId": "hotel-casa-do-largo-2026-11-06", "kind": "stay", "propertyToken": "...",
 "paidTotal": 318.0, "liveTotal": 262.0, "currency": "EUR", "offerSource": "Booking.com",
 "offerLink": "https://...", "offerFreeCancelUntil": "Nov 4", "checkedAt": "2026-10-15T20:00:00Z",
 "source": "Google Hotels via SearchApi"}
```

The build makes a `stay_price_drop` alert (info) when the stay is
`refundable: true`, its free cancellation has not ended, and the drop is at
least `stayDropMinimum`. The alert tells the user to check the room, book
the new rate first, and then cancel the old booking. Wayfare never books or
cancels.

## Manual items (added in a trip chat)

Items (dinners, tours, plans) added in a trip chat use the same booking objects with
`"source": "manual"` and an id that starts with `manual-`. Only these may be
changed or removed from a chat.

## Plan object

A trip that is not booked yet. Made with `/wayfare:plan`; checked by
`scripts/planner.py`. `planner.py validate` checks it.

```json
{"id": "teulada-2027-06", "title": "Wedding in Teulada", "purpose": "wedding",
 "status": "watching | paused | booked | ended",
 "destination": {"city": "Teulada", "country": "Spain", "event": "Wedding"},
 "travellers": {"adults": 2, "childrenAges": [5, 3]},
 "currency": "EUR",
 "flights": {"cabin": "economy | premium_economy | business | first", "maxStops": 0, "bags": "checked",
   "out":  {"from": ["AMS"], "to": ["ALC"], "date": "2027-06-10", "departAfter": "06:00", "departBefore": "12:00"},
   "back": {"from": ["ALC"], "to": ["AMS"], "date": "2027-06-13", "arriveBefore": "18:00"}},
 "stay": {"checkIn": "2027-06-10", "checkOut": "2027-06-13", "near": "Pueblo Mascarat, Altea", "city": "Altea",
   "nearLat": null, "nearLon": null, "minStars": 4, "maxDistanceKm": 20, "minRating": null,
   "freeCancellation": true, "rooms": 1, "kind": "hotel | apartment | villa", "preferred": ["Pueblo Mascarat"]},
 "notes": ["The couple recommends Pueblo Mascarat."],
 "alerts": {"minDropAmount": 20, "minDropPercent": 5},
 "booked": {"out": "<bookingId>", "back": null, "stay": null}}
```

- A plan needs `flights`, `stay`, or both. Each leg is optional. Leg times
  are local wall-clock times: `departAfter`/`departBefore` limit the
  departure, `arriveAfter`/`arriveBefore` the arrival (an arrival on the
  next day never meets `arriveBefore`). `airlines` (IATA codes) limits the
  airlines. `maxStops` null allows any.
- Flight prices are for all travellers: under 2 on a lap, 2 to 11 as
  children, 12 and over as adults. Stay prices are for all nights and all
  guests (one room in Google Hotels).
- `preferred` stays are always shown, even when they miss the stars or
  distance. Up to 2 are searched by name when the area search does not find
  them.
- `booked` is set by `planner.py reconcile` from real bookings; those parts
  are no longer searched.

Price record (`private/planprices` → `results.<planId>`): `checkedAt`,
`legs.out|back` = `{options, stats, cheapest}`, `stay` = `{options, stats,
cheapest, nights}`, `total`, and `history` = `{"out": [["2026-10-19", 620],
...], "back": [...], "stay": [...], "pref:<name>": [...], "total": [...]}`
(one point a day, newest 90).

Plan page database: `plan/data` (everyone the owner shares with reads it:
the wishes, options, prices and alerts; no personal data beyond the
travellers line), `private/data` (owner: `{agent: {triggerId}}`),
`requests/<id>` (owner). Alerts: `plan_flight_drop`, `plan_stay_drop`,
`plan_pref_drop` (info: the cheapest matching price fell by at least
`minDropAmount` and `minDropPercent` since the last check on an earlier
day), `plan_no_flights` and `plan_no_stays` (medium: nothing matches the
wishes).

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
