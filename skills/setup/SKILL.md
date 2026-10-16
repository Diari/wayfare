---
name: setup
description: Set up Wayfare, the open-source personal travel agent. Creates the private Wayfare Home page, saves the travel profile, creates the background tasks (the Wayfare agent for page buttons and an optional daily check), explains optional live-data keys and trip chats, then runs a first inbox sync (one shareable page per trip) or loads sample trips. Use when the user runs /wayfare:setup or asks to set up, repair or reset Wayfare.
---

# Wayfare setup

Wayfare reads travel confirmations from the user's Gmail and gives each trip
its own page that they can open on any device and share with the people on
the trip. Each page shows the trip day by day and flags problems: nights with
no stay booked, tight connections, schedule changes and what they break,
double bookings and fare drops. On the page they can mark problems done,
keep a shared to-do list, add the trip to their calendar, and ask Claude for
help (for example to find stays). Wayfare never books, cancels or pays.

Read `${CLAUDE_PLUGIN_ROOT}/reference/dashboard-io.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/data-model.md` first. `$P` means
`${CLAUDE_PLUGIN_ROOT}`.

Tell the user in one sentence what setup does and that it takes a few
minutes. Then do the steps in order. If Wayfare Home already exists, reuse it
and only repair what is missing (profile, agent task).

## 1. Wayfare Home

Look for it (dashboard-io.md, A). If missing:

```bash
mkdir -p wayfare-work && cp "$P/dashboard/home.html" wayfare-work/wayfare-home.html
python3 "$P/scripts/wayfare.py" capabilities --page home
```

`Artifact` publish: `file_path: wayfare-work/wayfare-home.html`,
`icon: "map"`, `description: "Your trips, with a page for each one."`,
`capabilities`: the JSON the second command printed, exactly.
Wayfare Home stays private: its rules let only the owner read it.

## 2. Travel profile

Ask in ONE plain-text message for:
- home airport code(s) and home city, for example "AMS, Amsterdam";
- anything Wayfare should know about how they like to fly, stay and eat
  (optional, free text).

Then, if `AskUserQuestion` is available, ask these in one call (otherwise in
plain text, accepting defaults):
- Minimum time to change flights: 60 / 75 (default) / 90 / 120 minutes.
- Minimum time from landing to a dinner booking: 90 / 150 (default) / 180 minutes.
- Smallest fare drop worth an alert, per traveller: 25 (default) / 50 / 100 in their currency.

Build the profile (data-model.md) and `ArtifactData` `set` it on Wayfare Home
at `private`/`profile` (if it exists, `get` it first and pass `if_version`).

## 3. Gmail

Check that a Gmail search tool (for example `search_threads`) is available,
loading it with tool search if deferred. If not: tell the user to connect
Gmail in Claude's settings under Connectors. Wayfare only opens emails that
look like bookings.

## 4. Background tasks

Find the scheduling tools with tool search (`create_trigger`,
`list_triggers`). If there are none, say that the page buttons that ask
Claude and the background checks stay off, and skip to step 5. Read Home
`private`/`agent` first; keep tasks that still exist (`list_triggers`).

1. **Wayfare agent** (page buttons). No schedule (no cron expression, no run
   time), `initiation: "human_request"`, prompt exactly:

   > You are the Wayfare agent. The text after this prompt starts with
   > WAYFARE_REQUEST and a JSON request from one of the user's Wayfare
   > pages; act on it as the agent skill says. Use the Wayfare plugin skill
   > `agent` (/wayfare:agent). If the Wayfare skills are not available,
   > follow the "Unattended runs" section of the plugin's
   > reference/dashboard-io.md. Work unattended: never ask questions.

2. **Wayfare daily check**. Ask once (default yes): "Should Wayfare check
   your inbox and flights every morning?" On yes: a daily schedule at about
   07:45 in the user's time zone (`CRON_TZ=<zone> <jittered minute> 7 * * *`),
   `initiation: "human_request"`, `notifications: {"push": true}`, prompt:

   > Run /wayfare:check daily. If the Wayfare skills are not available,
   > follow the "Unattended runs" section of the Wayfare plugin's
   > reference/dashboard-io.md. Work unattended: do not ask questions; skip
   > emails you are unsure about and list them at the end. End with "No
   > changes." when nothing changed.

   Each run uses some Claude usage, and the daily check also plans one-time
   "Wayfare watch" tasks 24 and 3 hours before each flight.

3. Save `{"triggerId": "<agent id>", "dailyTriggerId": "<id or null>",
   "repo": "<owner/repo of the Wayfare plugin, if known>", "createdAt": "<now>"}`
   to Wayfare Home `private`/`agent`. `repo` lets scheduled runs fetch the
   plugin when it is not installed there (dashboard-io.md H). Use the
   marketplace the user installed Wayfare from; if unknown, ask once.
4. Tell the user in one sentence which approval setting each task got. The
   tasks read Gmail, search the web and write to the pages with nobody there
   to approve, so if runs will ask, tell them to turn on "Automatically
   approve" in each task's settings, if their organization allows it.

## 4b. Live data keys (optional)

Ask once: "Do you want live flight status and fare checks? They need free
keys from Aviationstack and SearchApi." On yes, explain dashboard-io.md J in
plain steps: where to get each key, and where to put it (the cloud
environment's settings: an API credential for `www.searchapi.io`; the
variable `AVIATIONSTACK_ACCESS_KEY` plus network access Custom with
`api.aviationstack.com`). Never ask the user to paste a key into the chat.
Set `fareChecks: true` in the profile when they want fare checks.
Without keys, Wayfare still reads public flight pages for status.

## 4c. Trip chats

Say in one line: "For each trip you can open a new chat and type
/wayfare:trip <city>; that chat then gets the page buttons' results and the
travel-day alerts, and you can ask or add plans there."

## 5. First trips

Ask which they want (one question):
- **Sync my inbox now** (default when Gmail is connected): follow
  `$P/skills/sync/SKILL.md`.
- **Show sample trips first**: do dashboard-io.md B, then

  ```bash
  python3 "$P/scripts/wayfare.py" build --sample \
    --bookings "$P/samples/bookings.sample.json" --fares "$P/samples/fares.sample.json" \
    --profile "$P/samples/profile.sample.json" --agent wayfare-work/db/home/private/agent.json \
    --chats wayfare-work/db/home/private/chats.json \
    --index wayfare-work/db/home/index/trips.json \
    --versions wayfare-work/versions.json --out-dir wayfare-work/out
  ```

  then dashboard-io.md D, E and F. Sample pages show a "Sample trip" banner
  and never touch the real booking list. At the first real sync they stop
  updating; offer once to delete them then (only on the user's yes).

## 6. Finish

In three short lines: Wayfare Home is ready, each trip gets its own page
(both are in their Claude artifacts, so they open on the phone too), and how
to share a trip: the trip page's **Share** menu, inviting named people.
Invite people as **Contributor** if they should tick the to-do list.
Viewers need a Claude sign-in and never see full booking codes or prices.
