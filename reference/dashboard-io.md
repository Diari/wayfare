# Reading and writing the Wayfare pages

Shared steps for `/wayfare:setup`, `/wayfare:sync`, `/wayfare:fares` and the
agent. `$P` means `${CLAUDE_PLUGIN_ROOT}`. Work in a folder named
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
`private`/`agent`, and `index`/`trips`.

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

## Static fallback (no artifact tools)

```bash
python3 "$P/scripts/wayfare.py" render-static --owner \
  --bookings wayfare-work/bookings.json --profile wayfare-work/profile.json \
  --out-dir wayfare-work/pages
```

Keep `wayfare-work/bookings.json` and `wayfare-work/profile.json` as the
stored state. The files hold full codes and prices: do not share them.
Buttons that need Claude's runtime are hidden in these files.
