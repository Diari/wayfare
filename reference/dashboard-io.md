# Reading and writing the Wayfare pages

Shared steps for `/wayfare:setup`, `/wayfare:sync`, `/wayfare:check`,
`/wayfare:fares`, `/wayfare:trip` and the agent. `$P` means `${CLAUDE_PLUGIN_ROOT}`. Work in a folder named
`wayfare-work` in the current working directory.

## Tool names

- `Artifact`: `list`, `publish`. Pages are artifacts.
- `ArtifactData`: `get`, `list`, `set`, `update`, `batch` on a page's database.
  Some surfaces call these `read_db` / `write_db` on the `Artifact` tool.
  Load deferred tools with tool search first.
- No artifact tools at all (old Claude Code in a terminal): use the static
  fallback at the end.

## A. Find Wayfare Home

`Artifact` `list`, `scope: "mine"`, `limit: 50`. Wayfare Home is the artifact
titled exactly **Wayfare Home**. If there is none, tell the user to run
`/wayfare:setup` and stop. If there are several, use the newest and say so.

## B. Read the current state

All reads are safe. Use `out_dir` so the documents land in files.

Home (`out_dir: wayfare-work/db/home`):
`get` `private`/`profile`, `private`/`bookings`, `private`/`fares`,
`private`/`status`, `private`/`weather`, `private`/`chats`, `private`/`agent`,
and `index`/`trips`.

For each trip in `index/trips` whose `status` is `upcoming` or `ongoing` and
that has a `url`, on that trip page (`out_dir: wayfare-work/db/trips/<slug>`):
`get` `trip`/`data`, `get` `private`/`data`, `list` `actions`.

A missing document is normal. Each result shows the document `version`.
Write every version you saw to `wayfare-work/versions.json`:

```json
{
  "home":  {"index/trips": 5, "private/bookings": 5},
  "trips": {"lisbon-2026-11": {"trip/data": 3, "private/data": 3}}
}
```

List only documents that exist. The build pins every write with these.

## C. Build

```bash
python3 "$P/scripts/wayfare.py" build \
  --bookings wayfare-work/bookings.json \
  --profile  wayfare-work/db/home/private/profile.json \
  --fares    wayfare-work/db/home/private/fares.json \
  --status   wayfare-work/db/home/private/status.json \
  --chats    wayfare-work/db/home/private/chats.json \
  --weather  wayfare-work/db/home/private/weather.json \
  --index    wayfare-work/db/home/index/trips.json \
  --agent    wayfare-work/db/home/private/agent.json \
  --trips-db wayfare-work/db/trips \
  --versions wayfare-work/versions.json \
  --out-dir  wayfare-work/out
```

Missing input files are fine. It prints the trips and open alerts and writes
`wayfare-work/out/plan.json`. If it prints validation errors, fix the booking
JSON (re-read the source email if needed) and build again. Never delete a
booking to silence an error.

## D. Publish pages for new trips

For each entry in `plan.json` → `newTrips`, call `Artifact` publish with:
- `file_path`: the entry's `page`
- `icon`: `map`
- `description`: `<pageTitle>: bookings, gaps and alerts from Wayfare.`
- `capabilities`: the JSON in `wayfare-work/out/capabilities-trip.json`, exactly

Save each new page's url in `wayfare-work/urls.json` as
`{"<slug>": "<url>"}`. Never publish a page for a trip that already has one.

## E. Write each trip page

For each entry in `plan.json` → `trips`: `ArtifactData` `batch` with `url` =
the entry's `url` (or the new url from `urls.json`) and `writes` = the JSON
array in the entry's `batch` file, exactly as written.

## F. Write Wayfare Home

```bash
python3 "$P/scripts/wayfare.py" home-batch --out-dir wayfare-work/out --urls wayfare-work/urls.json
```

Then `ArtifactData` `batch` on the Wayfare Home url with
`wayfare-work/out/home/batch.json`.

If any batch fails because a version changed, read that page again
(section B), rebuild, and write once more. Do not retry more than once; tell
the user instead.

## G. Report

In a few short lines: new trip pages, changed and cancelled bookings, then
open urgent alerts. Do not paste timelines; the pages show them. Do not
repeat booking codes in chat unless the user asks.

## H. Unattended runs (scheduled tasks and page requests)

A scheduled task starts a fresh cloud session. Tested in October 2026:
installed plugins are NOT loaded there, but Gmail, Google Calendar, the
artifact tools, web search and web fetch are, and writes to the Wayfare
pages work without approval. The session's network reaches GitHub, but not
outside APIs unless the environment allows them (dashboard-io.md J).

Before anything else:

1. If the `/wayfare:...` skills are available, use them.
2. Otherwise read `repo` from Wayfare Home `private`/`agent` (for example
   `owner/wayfare`) and run `git clone --depth 1 https://github.com/<repo>.git
   wayfare-plugin`. Then `$P` is `wayfare-plugin`, and you follow the skill
   files in `wayfare-plugin/skills/` directly.
3. If neither works, stop and report "The Wayfare plugin is not available in
   scheduled runs" in the request status or the task output.

Never ask questions. Never book, pay, change or cancel anything.

## I. Record changes for the user

When a check finds something new that needs the user's attention (a new
trip, a new or changed booking, a new high or medium alert, a delay or a
cancellation), append it to Home `private`/`changes`:
`{"items": [{"at": "<now ISO>", "slug": "<slug>", "summary": "<one or two plain sentences>"}, ...]}`
(keep the newest 50; `set` with `if_version`). Do not record "nothing
changed".

The task's push notification tells the user right away. A trip chat reads
these changes when the user next writes in it.

Scheduled runs do not ring a trip chat's doorbell: in tests they would not
start another task. Only the page buttons ring it (the user's own click).

## J. Keys for live data (optional)

| What | Service | How the key gets to the run |
|------|---------|-----------------------------|
| Live fares | SearchApi, Google Flights engine (`www.searchapi.io`) | Best: an **API credential** on the cloud environment for `www.searchapi.io` (Bearer). The key never reaches Claude. Or `SEARCHAPI_API_KEY`. |
| Flight status | Aviationstack (`api.aviationstack.com`) | Takes the key as a URL parameter, so a header credential does not work: set `AVIATIONSTACK_ACCESS_KEY` in the environment's variables and allow `api.aviationstack.com` (Network access: Custom, keep the default list). |
| Weather | Open-Meteo (free, no key) | Allow `api.open-meteo.com`, `geocoding-api.open-meteo.com` and `archive-api.open-meteo.com` (Network access: Custom). |
| No key | Public flight page | The check skill reads `https://www.flightradar24.com/data/flights/<flight>` with the web fetch tool and writes the same status record by hand. |

## Static fallback (no artifact tools)

```bash
python3 "$P/scripts/wayfare.py" render-static --owner \
  --bookings wayfare-work/bookings.json --profile wayfare-work/profile.json \
  --out-dir wayfare-work/pages
```

Keep `wayfare-work/bookings.json` and `wayfare-work/profile.json` as the
stored state. The files hold full codes and prices: do not share them.
Buttons that need Claude's runtime are hidden in these files.
