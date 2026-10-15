# Reading and writing the Wayfare dashboard

Shared steps for `/wayfare:setup`, `/wayfare:sync` and `/wayfare:fares`.
`$P` below means `${CLAUDE_PLUGIN_ROOT}`. Work in a folder named
`wayfare-work` in the current working directory.

## Tool names

The artifact database tool is `ArtifactData` (actions `get`, `list`, `set`,
`batch`). Some Claude surfaces call it through the `Artifact` tool as
`read_db` / `write_db`. If it is deferred, load it first. If no artifact tool
exists at all (for example an old Claude Code in a terminal), use the static
fallback at the end of this file.

## A. Find the dashboard

1. Call `Artifact` with `action: "list"`, `scope: "mine"`, `limit: 50`.
2. The dashboard is the artifact titled exactly **Wayfare Trips**. Remember
   its `url`.
3. None found: tell the user to run `/wayfare:setup` first and stop.
4. More than one: use the most recently updated one and say so.

## B. Read the current state

Run these reads (they are safe and need no approval):

- `ArtifactData` `get` `private` / `profile`, `out_dir: wayfare-work/db`
- `ArtifactData` `get` `private` / `bookings`, `out_dir: wayfare-work/db`
- `ArtifactData` `get` `private` / `fares`, `out_dir: wayfare-work/db`
- `ArtifactData` `get` `meta` / `status`, `out_dir: wayfare-work/db`
- `ArtifactData` `list` `trips`, `out_dir: wayfare-work/db`

A missing document is normal on a new dashboard. Each result line shows the
document's `version`. Write every version you saw into
`wayfare-work/versions.json`, keyed `"<collection>/<doc_id>"`, for example:

```json
{"trips/lisbon-2026-11": 3, "meta/status": 7, "private/bookings": 7, "private/profile": 1}
```

Only list documents that exist. The build step uses this file to pin every
write and to delete trips that are gone.

## C. Build

```bash
python3 "$P/scripts/wayfare.py" build \
  --bookings wayfare-work/bookings.json \
  --profile wayfare-work/db/private/profile.json \
  --fares wayfare-work/db/private/fares.json \
  --versions wayfare-work/versions.json \
  --out-dir wayfare-work/out
```

Leave out `--fares` or `--profile` if that file does not exist. The command
prints the trips and alerts and writes `wayfare-work/out/batch.json`.
If it prints validation errors, fix the booking JSON (re-read the source
email if needed) and run it again. Never delete a booking to silence an error.

## D. Write

Read `wayfare-work/out/batch.json`. Call `ArtifactData` with
`action: "batch"`, the dashboard `url`, and `writes` set to that array exactly
as written (entries use `file_path`, so the call stays small).

If the batch fails because a version changed, do section B again, rebuild,
and write once more. Do not retry more than once; tell the user instead.

## E. Report

Tell the user in a few short lines: what changed, then urgent alerts first.
Do not paste the whole timeline; the page shows it. Do not repeat booking
codes in chat unless the user asks.

## Static fallback (no artifact tool)

```bash
python3 "$P/scripts/wayfare.py" render-static --owner \
  --bookings wayfare-work/bookings.json \
  --profile wayfare-work/profile.json \
  --out wayfare-work/wayfare-trips.html
```

Keep `wayfare-work/bookings.json` and `wayfare-work/profile.json` as the
stored state in this mode. The file contains full codes and prices: do not
share it.
