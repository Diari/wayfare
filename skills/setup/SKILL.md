---
name: setup
description: Set up Wayfare, the open-source personal travel agent. Creates the private "Wayfare Trips" dashboard page, saves the user's travel profile, then runs a first inbox sync or loads sample trips. Use when the user runs /wayfare:setup or asks to set up or reset Wayfare.
---

# Wayfare setup

Wayfare reads travel confirmations from the user's Gmail, builds each trip on
a private dashboard page they can open on any device and share, and flags
problems: nights with no stay booked, tight connections, schedule changes and
what they break, double bookings and fare drops. It never books, cancels or
pays for anything.

Before you start, read `${CLAUDE_PLUGIN_ROOT}/reference/dashboard-io.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/data-model.md`.

Tell the user in one sentence what setup does and that it takes about two
minutes. Then do the steps in order.

## 1. Dashboard page

1. Look for an existing dashboard (dashboard-io.md, section A). If one exists,
   reuse it: say so and go to step 2. Do not create a second one.
2. Otherwise copy the page into the working directory and publish it:

   ```bash
   mkdir -p wayfare-work && cp "${CLAUDE_PLUGIN_ROOT}/dashboard/index.html" wayfare-work/wayfare-trips.html
   ```

   Call `Artifact` (publish) with:
   - `file_path`: `wayfare-work/wayfare-trips.html`
   - `icon`: `map`
   - `description`: `Your trips from Wayfare: bookings, gaps and alerts.`
   - `capabilities` exactly:
     `{"db": {"rules": [{"path": "", "read": "view", "write": "owner"}, {"path": "private", "read": "owner", "write": "owner"}]}, "user": {}}`

   The page is private to the user until they share it.

## 2. Travel profile

Ask in ONE message (plain text) for:
- home airport code(s) and home city, for example "AMS, Amsterdam";
- anything Wayfare should know about how they like to fly, stay and eat
  (optional, free text).

Then, if `AskUserQuestion` is available, ask these in one call (otherwise ask
in plain text and accept defaults when the user skips):
- Minimum time to change flights: 60 / 75 (default) / 90 / 120 minutes.
- Minimum time from landing to a dinner booking: 90 / 150 (default) / 180 minutes.
- Smallest fare drop worth an alert, per traveller: 25 (default) / 50 / 100 in their home currency.

Build the profile object from data-model.md (`homeAirports` upper-case IATA
codes; `currency` from their home country) and write it:
`ArtifactData` `set`, `collection: "private"`, `doc_id: "profile"`,
`data: <profile>`. If the document already exists, `get` it first and pass
its `version` as `if_version`.

## 3. Gmail

Check whether a Gmail tool for searching threads (for example
`search_threads`) is available, loading it with tool search if it is
deferred. If not, tell the user: connect Gmail in Claude's settings under
Connectors, then run `/wayfare:sync`. Explain that Wayfare only opens emails
that look like travel bookings.

## 4. First data

Ask which they want (one question):
- **Sync my inbox now** (default when Gmail is connected): follow
  `${CLAUDE_PLUGIN_ROOT}/skills/sync/SKILL.md`.
- **Show sample trips first**: run

  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wayfare.py" build --sample \
    --bookings "${CLAUDE_PLUGIN_ROOT}/samples/bookings.sample.json" \
    --fares "${CLAUDE_PLUGIN_ROOT}/samples/fares.sample.json" \
    --profile "${CLAUDE_PLUGIN_ROOT}/samples/profile.sample.json" \
    --versions wayfare-work/versions.json --out-dir wayfare-work/out
  ```

  (do dashboard-io.md section B first so `versions.json` exists), then write
  the batch (section D). With `--sample` the batch does not touch
  `private/bookings`, so sample data never mixes with real bookings. The page
  shows a "Sample trips" banner, and the first real sync replaces them.

## 5. Keep it fresh (optional)

Offer once: "Should I check your inbox for new bookings every morning?"
On yes, create a scheduled task with the session's scheduling tools (search
for them with tool search if needed): daily, around 07:00 in the user's time
zone, prompt: `Run /wayfare:sync. Work unattended: do not ask questions; skip
emails you are unsure about and list them at the end.` Say that each run uses
some of their Claude usage. If no scheduling tool exists, say they can run
`/wayfare:sync` any time.

## 6. Finish

In two or three lines: the dashboard is ready (the app shows its card), how
to open it on the phone (it is in their Claude artifacts), and how to share
it: the page's **Share** menu, inviting named people. Shared viewers need a
Claude sign-in and never see full booking codes or prices.
