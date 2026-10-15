# Wayfare

Wayfare is an open-source personal travel agent for Claude. It is a Claude
plugin. It runs in your own Claude account, with your own Gmail. There is no
Wayfare server.

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
  - lower fares on the same flight (optional, needs your own Duffel token).
- On a trip page you can:
  - mark a problem **Done**, **Not a problem** or **Later** (it comes back
    if the facts change),
  - open ready-made links: a stay search with the city and dates filled in,
    the map, the provider's manage-booking page,
  - keep a **to-do list** that people you invite as Contributors can tick,
  - **add the trip to your Google Calendar**,
  - **ask Claude** to find stays for unbooked nights, check your inbox or
    check fares. The result appears on the page a few minutes later.

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
| `/wayfare:fares` | Optional, experimental. Looks for lower fares on your booked flights with the Duffel API. |
| `/wayfare:agent` | Used by the "Wayfare agent" task to answer page buttons. You do not run it yourself. |

## Install

### Claude Code

```text
/plugin marketplace add <github-user>/wayfare
/plugin install wayfare@wayfare
```

Then run `/wayfare:setup`.

### Claude app (desktop and mobile)

Add this repository as a plugin marketplace in the app's plugin settings,
install **Wayfare**, then type `/wayfare:setup` in a chat. Connect **Gmail**
under Settings → Connectors first.

## Requirements

- A Claude account with artifacts and the **Gmail** connector.
- Optional: the **Google Calendar** connector, for "Add to my calendar".
- Optional: scheduled tasks, for the "Ask Claude" buttons and a daily sync.
  Setup creates a task named "Wayfare agent". Turn on "Automatically approve"
  for it, because nobody is there to approve its steps.
- Optional, for `/wayfare:fares`: a Duffel account, `DUFFEL_ACCESS_TOKEN` in
  your environment, and Claude Code on your own computer (cloud sessions
  usually cannot reach outside APIs). Duffel can charge $0.005 per search
  when you search much more than you book through Duffel.

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
```

The sample bookings are invented. Any match with real places is chance.

## Roadmap

- Codex / ChatGPT plugin with a Sites dashboard.
- Hotel price drops for refundable stays.
- Watch for sold-out stays and tables.
- Edit your profile on Wayfare Home.

## License

MIT
