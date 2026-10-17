---
name: wayfare-check
description: The Wayfare background check for ChatGPT and Codex. "daily" reads Gmail, gets weather, live flight status and fares, writes guides, updates and redeploys the trip Sites and plans travel-day watches; "inbox" handles new booking emails; "watch" checks flights close to departure. Use when a Wayfare scheduled task runs or the user asks Wayfare to check now.
---

# Wayfare check

Read `../../reference/sites-io.md` (relative to this file) and
`../../reference/data-model.md`. Work unattended when a task started this
run: never ask questions. Load keys if `$WF/.env` exists
(`set -a; . "$WF/.env"; set +a`, never print it).

Modes (the text after the skill name):
- `daily` (default): steps 1 to 7.
- `inbox`: steps 1, 5 and 6 (a new email arrived).
- `watch [<bookingId>]`: steps 2, 5 and 6, for that flight or for all
  flights that leave in the next 30 hours.

## 1. Inbox

Follow `../wayfare-sync/SKILL.md` steps 1 to 4.

## 2. Live flight status

```bash
python3 "$P/scripts/flight_status.py" --bookings "$WF/bookings.json" \
  --previous "$WF/status.json" --out "$WF/status.json"
```

(watch mode: add `--min-age-minutes 20`). Without `AVIATIONSTACK_ACCESS_KEY`,
read `https://www.flightradar24.com/data/flights/<flight, lower case>` for
each due flight (at most 3) and write the status record by hand, as
data-model.md "Status record" says. Write only what the page shows.

## 3. Weather (daily)

```bash
python3 "$P/scripts/wayfare.py" weather-plan --bookings "$WF/bookings.json" \
  --profile "$WF/profile.json" > "$WF/weather-plan.json"
python3 "$P/scripts/weather.py" --plan "$WF/weather-plan.json" \
  --previous "$WF/weather.json" --out "$WF/weather.json"
```

## 4. Fares and stay prices (daily, only if `profile.json` has `fareChecks: true`)

```bash
python3 "$P/scripts/fare_check.py" --provider searchapi --bookings "$WF/bookings.json" \
  --previous "$WF/fares.json" --out "$WF/fares.json" --every-days 3 --max-searches 6
python3 "$P/scripts/stay_check.py" --bookings "$WF/bookings.json" \
  --previous "$WF/fares.json" --out "$WF/fares.json" --every-days 2 --max-stays 4
```

The second command finds a lower price with free cancellation for each
refundable stay (Google Hotels via SearchApi).

## 4b. Guides (daily)

For each upcoming trip, follow `../wayfare-guide/SKILL.md` section 2 to
decide if its guide needs writing; at most 2 per run.

## 5. Build and publish

sites-io.md, "Build the Sites" and "Publish with Sites" (redeploy only the
Sites marked new or changed).

## 6. Tell the user, only about changes

Compare the open alerts with the ones from the last run (keep them in
`$WF/last-alerts.json`: `{slug: [alert ids]}`). A change is a new trip, a
new or changed booking, or a new high or medium alert (including
`flight_delayed` and `flight_cancelled`). Append each change to
`$WF/changes.json`. The run's last message is the notification: at most
three short lines, most urgent first, or exactly `No changes.`

## 7. Travel-day watches (daily)

For each flight that leaves in the next 72 hours and is not cancelled,
create one-time scheduled tasks in the `$WF` project at 24 hours and 3
hours before departure, named `Wayfare watch <bookingId> <hours>h`, prompt
`$wayfare-check watch <bookingId>`, unless one with that name exists or the
time is past. At most 6 per run.
