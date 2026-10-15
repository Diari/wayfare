# Wayfare

Wayfare is an open-source personal travel agent for Claude. It is a Claude
plugin. It runs in your own Claude account, with your own Gmail. There is no
Wayfare server.

**What it does**

- Reads travel confirmations from your Gmail: flights, trains, stays and
  restaurant tables. It opens only emails that look like bookings.
- Builds each trip on a private dashboard page (a Claude artifact). You can
  open the page on your phone or computer and share it with named people.
- Finds problems:
  - nights with no stay booked,
  - connections shorter than your minimum,
  - schedule changes, and what they break (a dinner you now miss, a hotel
    check-in day you now miss),
  - two stays booked for the same night,
  - lower fares on the same flight (optional, needs your own Duffel token).

**What it does not do**

- It never books, changes, cancels or pays for anything. To act on an alert,
  you go to the airline, hotel or restaurant yourself.
- Shared viewers never see full booking codes or prices. (A booking code and
  a last name are enough to change a flight on an airline website.)

## Commands

| Command          | What it does |
|------------------|--------------|
| `/wayfare:setup` | Makes the dashboard page, asks for your travel profile, then syncs your inbox or loads sample trips. Can also set a daily sync. |
| `/wayfare:sync`  | Reads new bookings, changes and cancellations from Gmail and updates the page. |
| `/wayfare:fares` | Optional, experimental. Looks for lower fares on your booked flights with the Duffel API. |

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

- A Claude account with artifacts and the Gmail connector.
- For `/wayfare:fares`: a Duffel account, `DUFFEL_ACCESS_TOKEN` set in your
  environment, and Claude Code on your own computer (cloud sessions usually
  cannot reach outside APIs). Duffel can charge $0.005 per search when you
  search much more than you book through Duffel.

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
      ──(scripts/wayfare.py: merge, check, redact)──> dashboard documents
      ──(ArtifactData batch write)──> "Wayfare Trips" page
```

- `skills/` tell Claude what to do for each command.
- `scripts/wayfare.py` does the exact work: validation, trip grouping, gap and
  conflict checks, redaction. Python standard library only.
- `scripts/fare_check.py` is the optional Duffel fare check.
- `dashboard/index.html` is the page. It reads the artifact database, so it
  stays read-only for everyone and updates live.

## Develop

```bash
python3 -m unittest discover -s tests -v
python3 scripts/wayfare.py render-static --bookings samples/bookings.sample.json \
  --profile samples/profile.sample.json --fares samples/fares.sample.json \
  --now 2026-10-15T20:00:00+00:00 --out /tmp/wayfare.html
claude plugin validate . --strict
```

The sample bookings are invented. Any match with real places is chance.

## Roadmap

- v0.2: Codex / ChatGPT plugin with a Sites dashboard.
- Hotel price drops for refundable stays.
- Watch for sold-out stays and tables.
- Edit your profile on the page.

## License

MIT
