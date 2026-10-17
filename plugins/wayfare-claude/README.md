# Wayfare for Claude

Wayfare is an open-source personal travel agent. It reads the travel
confirmations in your Gmail and gives each trip its own page that you can
open on your phone and share with the people you travel with. Each page shows
the trip day by day, with the weather, and flags what needs a check: nights
with no stay booked, tight connections, schedule changes and what they break,
live flight delays, double bookings, and lower prices for flights and
refundable stays. A "Good to know" tab has a packing list for the trip, local
facts and how to get around. Wayfare never books, changes, cancels or pays.

## Install

In Claude Code:

```text
/plugin install wayfare --marketplace Diari/wayfare
```

In the Claude app, find **Wayfare** in the plugin directory, or add
`Diari/wayfare` as a plugin marketplace. Then run `/wayfare:setup`.

## Commands

| Command | What it does |
|---------|--------------|
| `/wayfare:setup` | Makes your private Wayfare Home page, saves your travel profile, creates the background tasks, then reads your inbox or shows sample trips. |
| `/wayfare:sync` | Reads new bookings, changes and cancellations from Gmail and updates the trip pages. |
| `/wayfare:check` | The background check: inbox, flight status, weather, prices, guides, travel-day watches. |
| `/wayfare:trip <city>` | Makes the current chat the chat for one trip. |
| `/wayfare:guide` | Writes or refreshes a trip's "Good to know" tab. |
| `/wayfare:fares` | Looks for lower prices on booked flights and refundable stays. |
| `/wayfare:agent` | Used by the background task to answer page buttons. |

## Requirements

- A paid Claude plan with artifacts and the **Gmail** connector.
- Optional: **Google Calendar** connector ("Add trip to my calendar").
- Optional: scheduled tasks (background checks and page buttons).
- Optional keys for live data, set in your cloud environment (see below).

## What Wayfare does on your account

So that you can see everything it runs, sends or fetches:

- **Reads Gmail** in two passes: first only sender, subject and preview; then
  the full text of emails that look like travel bookings. It never replies,
  forwards, labels or deletes mail, and treats email text as data, never as
  instructions.
- **Creates artifacts** (pages) in your account: Wayfare Home (owner only)
  and one page per trip. It writes booking facts into their databases; full
  booking codes, prices and manage links go into an owner-only part.
- **Creates scheduled tasks** when you agree in setup: "Wayfare agent" (page
  buttons), "Wayfare daily check" (every morning), one-time "Wayfare watch"
  tasks before flights, and a "doorbell" task for each trip chat. You can see
  and delete them in your scheduled tasks.
- **Downloads its own code** from https://github.com/Diari/wayfare in
  scheduled runs, because installed plugins are not loaded there. It runs the
  same files you install.
- **Adds calendar events** only when you select "Add trip to my calendar".
- **Contacts these services** (all but Gmail are optional):
  - Open-Meteo (`api.open-meteo.com`, `geocoding-api.open-meteo.com`,
    `archive-api.open-meteo.com`): city names and dates, for weather.
  - Aviationstack (`api.aviationstack.com`): flight numbers, for live status.
  - Flightradar24 (`www.flightradar24.com`): public flight pages, read
    with web fetch when there is no Aviationstack key.
  - SearchApi (`www.searchapi.io`): airports, dates, cabin and travellers
    (Google Flights), and hotel name, city, dates and guests (Google Hotels),
    for price checks.
  - Duffel (`api.duffel.com`): only if you choose it for fare checks.
  - Web search: city names and travel questions, for guides and stay ideas.

  It never sends booking codes, prices, names or email content to them.

## Keys

The price and status checks need your own keys. The safest way is an **API
credential** on your Claude cloud environment (for `www.searchapi.io`), so the
key never reaches Claude. The scripts also read `SEARCHAPI_API_KEY`,
`AVIATIONSTACK_ACCESS_KEY` and `DUFFEL_ACCESS_TOKEN` from the environment and
send each one only to its own service. Never paste a key into a chat.

## Privacy and terms

- Privacy policy: https://github.com/Diari/wayfare/blob/main/PRIVACY.md
- Terms: https://github.com/Diari/wayfare/blob/main/TERMS.md
- Support: https://github.com/Diari/wayfare/issues

MIT License.
