# Wayfare

<p align="center">
  <a href="docs/media/wayfare-showreel.mp4">
    <img src="docs/media/wayfare-showreel.gif" alt="Wayfare in one minute: it reads booking emails, builds a page per trip, flags what breaks, watches your flights and shares the trip" width="100%">
  </a>
</p>

<p align="center"><b>Your open-source travel agent for Claude, ChatGPT and Codex.</b><br>
Reads your booking emails · one page per trip · alerts when something breaks · never books or pays<br>
<a href="docs/media/wayfare-showreel.mp4">Watch the 1-minute showreel in HD, with sound</a></p>

Wayfare is an open-source personal travel agent. It is a plugin for
**Claude** (trip pages are Claude artifacts) and for **ChatGPT and Codex**
(trip pages are ChatGPT Sites). It runs in your own account, with your own
Gmail. There is no Wayfare server.

## At a glance

| | |
|---|---|
| **1. It reads your Gmail** | Two passes: sender and subject first, and it opens only real bookings. Newsletters, invoices and personal mail stay closed. |
| **2. It builds a page per trip** | Day by day: every flight, train, stay and table, with the journey at a glance. Open it on your phone or share it. |
| **3. It finds what breaks** | Schedule changes and what they break, nights with no stay, tight connections, double bookings, lower fares. |
| **4. It keeps watch** | A daily check every morning, live status 24 h and 3 h before each flight, and a phone ping only when something changed. |
| **5. It is ready to share** | Weather per day, a pack list, local tips, a shared to-do list. Shared viewers never see booking codes or prices. |

## Quick start (Claude)

Using ChatGPT or Codex? See [Install](#install) below.

1. **Connect Gmail** in Claude: Settings → Connectors → Gmail.
   (Optional: Google Calendar, for "Add to my calendar".)
2. **Install the plugin.** In Claude Code:

   ```text
   /plugin marketplace add Diari/wayfare
   /plugin install wayfare@wayfare
   ```

   In the Claude app, add `Diari/wayfare` as a plugin marketplace in the
   plugin settings and install **Wayfare**.
3. **Run `/wayfare:setup`** in a chat. It makes your private Wayfare Home
   page, asks a few questions for your travel profile (home airport,
   minimum connection time, stay style), and reads your inbox. No travel
   mail yet? It loads two sample trips so you can look around.
4. **Turn on the background checks** (optional). Setup creates the
   "Wayfare daily check" and "Wayfare agent" scheduled tasks. Open each one
   and turn on **Automatically approve**, because nobody is there to approve
   their steps.
5. **Open a trip chat** (optional): start a new chat and type
   `/wayfare:trip Lisbon`. Page buttons and background checks report there.

That is all. New bookings appear on their own after the next daily check,
or right away with `/wayfare:sync`.

**What it does**

- Reads travel confirmations from your Gmail: flights, trains, stays and
  restaurant tables. It opens only emails that look like bookings.
- Gives each trip **its own page** (a Claude artifact). You can open it on
  your phone or computer and share it with the people on that trip.
  A private **Wayfare Home** page lists all your trips.
- Finds problems:
  - nights with no stay booked,
  - connections shorter than your minimum,
  - schedule changes, and what they break (a dinner you now miss, a hotel
    check-in day you now miss),
  - two stays booked for the same night,
  - live flight delays, cancellations, terminal, gate and bags belt, and
    what a delay breaks (a connection, a dinner, a hotel check-in),
  - lower fares on the same flight (optional, Google Flights prices through
    your own SearchApi key),
  - a lower price for a refundable stay, with free cancellation, for the
    same hotel and dates (optional, Google Hotels through SearchApi). Wayfare
    tells you to book the new rate first and only then cancel the old one.
- **Weather** for each day of the trip (Open-Meteo, free, no key): a
  forecast for the next 16 days, and last year's weather on the same dates
  for later days. Wayfare Home shows it on each trip card.
- A **Good to know** tab on each trip, written by Claude from a web search:
  what to pack for that weather and your plans (each person ticks their own
  list), money, plugs, tipping, emergency number, a few words, time
  difference, and how to get around each city (airport to centre, transit
  cards, tips for your booked trains), plus a map route for each day.
- Works in the background: a **daily check** every morning (Gmail, live
  status, fares) and **travel-day watches** 24 and 3 hours before each
  flight. You get a phone notification only when something changed.
- **One chat per trip**: open a new chat and type `/wayfare:trip Lisbon`.
  Page buttons then send their requests and results to that chat, it sums
  up what the background checks found, and you can ask questions or add
  plans there.
- Scheduled runs do not load installed plugins. They fetch Wayfare from its
  GitHub repository instead, so the background checks need the repository
  to be public (or reachable by your Claude GitHub access).
- Each booking type looks different, with its own icon and color: a flight
  is a boarding pass, a train has a track line, a stay shows its nights, a
  table is a reservation card. A journey line shows the whole trip.
- One simple view: **day by day**. A short header shows the dates, the
  travellers, the journey and how many things need a check.
- A problem shows inside the booking it is about, with **one button** for the
  most useful next step (for example "Check the new time" or "Search stays").
  All other actions for that booking are in its **⋯** menu. Trip-wide actions
  (add to calendar, check inbox, check fares, show codes) are in the **⋯** menu
  at the top.
- On a trip page you can:
  - mark a problem **handled**, **not a problem** or **remind me in 3 days** (it comes back
    if the facts change),
  - open ready-made links: a stay search with the city and dates filled in,
    the map, the provider's manage-booking page,
  - keep a **to-do list** that people you invite as Contributors can tick,
  - **add the trip to your Google Calendar**,
  - **ask Claude** to find stays for unbooked nights, check your inbox,
    check flight status or check fares. The result appears on the page a
    few minutes later (and in the trip chat, if the trip has one).

**What it does not do**

- It never books, changes, cancels or pays for anything. Links take you to
  the airline, hotel or restaurant; you finish there.
- Shared viewers never see full booking codes, prices or your private
  manage-booking links. (A booking code and a last name are enough to change
  a flight on an airline website.)

## Commands

| Command          | What it does |
|------------------|--------------|
| `/wayfare:setup` | Makes Wayfare Home, asks for your travel profile, creates the "Wayfare agent" task the page buttons use, then syncs your inbox or loads sample trips. |
| `/wayfare:sync`  | Reads new bookings, changes and cancellations from Gmail. Updates trip pages and makes pages for new trips. |
| `/wayfare:check` | The background check: Gmail, live flight status, fares, page updates, travel-day watches. `/wayfare:check watch` checks only flights that leave in the next 30 hours. |
| `/wayfare:trip`  | Makes the current chat the chat of one trip. |
| `/wayfare:guide` | Writes or refreshes a trip's "Good to know" tab. |
| `/wayfare:fares` | Optional. Looks for lower fares on your booked flights (SearchApi, or Duffel). |
| `/wayfare:agent` | Used by the "Wayfare agent" task to answer page buttons. You do not run it yourself. |

## Install

### Claude Code

```text
/plugin marketplace add Diari/wayfare
/plugin install wayfare@wayfare
```

Then run `/wayfare:setup`.

### Claude app (desktop and mobile)

Add this repository as a plugin marketplace in the app's plugin settings,
install **Wayfare**, then type `/wayfare:setup` in a chat. Connect **Gmail**
under Settings → Connectors first.

### ChatGPT and Codex (Sites)

In the ChatGPT desktop app (Codex):

```text
codex plugin marketplace add Diari/wayfare
```

Then install **Wayfare** from the Plugins directory, connect the **Gmail**
plugin, and ask: "Set up Wayfare for my trips" (`$wayfare-setup`).

- Each trip is a **ChatGPT Site**, plus a private **Wayfare Home** Site. A
  Site's facts are rebuilt and redeployed after each check; what people do
  on it (handled problems, to-dos, their own packing ticks) is kept in the
  Site's own database.
- Viewers sign in with ChatGPT. The owner (the email you give at setup) sees
  full booking codes and manage links; people you share with never do.
- A **calendar file** (.ics) replaces "add to calendar".
- **Site tools**: when you open a trip Site in the ChatGPT app's browser,
  ChatGPT can read the trip, mark a problem as handled or add a to-do.
- Scheduled tasks in the app: a **daily check**, a check on **new booking
  emails** (Plus and Pro), and **travel-day watches**. They run on your
  computer, so it must be on with the app running.
- Use `$wayfare-trip Lisbon` in a chat to make it the chat for that trip.
- Sites needs a Plus, Pro or eligible workspace plan and is not available in
  every region; check that you see **Sites** in ChatGPT. Without Sites you can
  still preview a trip page locally (`node dev.mjs` in its Site folder).

The Codex plugin is in `plugins/wayfare/` and shares the engine, pages and
samples with the Claude plugin (`python3 tools/sync_codex.py` copies them).

## Requirements

- A Claude account with artifacts and the **Gmail** connector.
- Optional: the **Google Calendar** connector, for "Add to my calendar".
- Optional: scheduled tasks, for the "Ask Claude" buttons, the daily check
  and travel-day watches. Setup creates "Wayfare agent" and "Wayfare daily
  check". Turn on "Automatically approve" for them, because nobody is there
  to approve their steps. Each run uses some of your Claude usage.
- Optional live data keys, set on the cloud environment (claude.ai/code →
  environment selector → settings):
  - **SearchApi** (live fares, Google Flights engine): add an **API
    credential** for `www.searchapi.io`. The key never reaches Claude.
    100 free searches, then about $4 per 1,000.
  - **Aviationstack** (delays, gates, cancellations): set
    `AVIATIONSTACK_ACCESS_KEY` in the environment variables and allow
    `api.aviationstack.com` (Network access: Custom, keep the default list).
    It takes the key in the URL, so a header credential does not work.
    100 free requests a month; real-time data only (today and tomorrow).
  - Without keys, Wayfare reads the public Flightradar24 page for status.
  - **Weather** (Open-Meteo, free, no key): allow `api.open-meteo.com`,
    `geocoding-api.open-meteo.com` and `archive-api.open-meteo.com`.
- Duffel still works for fares (`--provider duffel`, `DUFFEL_ACCESS_TOKEN`).

## Privacy

- Two-pass reading: Wayfare first looks only at sender and subject. It opens
  the full email only for travel bookings.
- It stores only booking facts (see `reference/data-model.md`), never email
  text.
- All data stays in the database of your own dashboard artifact. Booking codes
  and prices are in an owner-only part of that database.
- Email content is treated as untrusted data: Wayfare ignores instructions in
  emails and never follows their links.

## How it works

```text
Gmail ──(Claude reads bookings)──> bookings JSON
      ──(scripts/wayfare.py: merge, group into trips, check, redact)──> one batch per page
      ──(ArtifactData)──> Wayfare Home + one page per trip

Trip page button ──(Claude Code Remote: fire the "Wayfare agent" task)──> Claude run
      ──(skills/agent)──> results written back to the page
```

- `skills/` tell Claude what to do for each command.
- `scripts/wayfare.py` does the exact work: validation, trip grouping and
  matching (a trip keeps its page when it grows), gap and conflict checks,
  alert ids, links, redaction. Python standard library only.
- `dashboard/trip.html` and `dashboard/home.html` are the pages. They read the
  page database live. Access rules decide who can write what.

## Develop

```bash
python3 -m unittest discover -s tests -v
python3 scripts/wayfare.py render-static --owner --bookings samples/bookings.sample.json \
  --profile samples/profile.sample.json --fares samples/fares.sample.json \
  --now 2026-10-15T20:00:00+00:00 --out-dir /tmp/wayfare-pages
claude plugin validate . --strict
python3 tools/sync_codex.py && python3 tools/validate_codex.py
```

Preview a trip Site locally (Node 22+):

```bash
python3 scripts/wayfare.py site-bundle --sample --bookings samples/bookings.sample.json \
  --profile samples/profile.sample.json --sites-dir /tmp/wayfare-sites
cd /tmp/wayfare-sites/lisbon-2026-11 && OWNER_EMAIL=me@example.com DEV_EMAIL=me@example.com node dev.mjs
```

The sample bookings are invented. Any match with real places is chance.

## Roadmap

- Train status: NS API (Netherlands) and Deutsche Bahn Timetables API. Both
  are free and use header keys, so they work as API credentials.
- Better flight status: AeroDataBox (cheap, future flights) or FlightAware
  AeroAPI (best data, paid).
- Watch for sold-out stays and tables.
- Edit your profile on Wayfare Home.

## License

MIT
