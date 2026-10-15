---
name: fares
description: Optional and experimental. Check whether the same flights the user already booked now sell for less, using the user's own Duffel API token, and add fare-drop alerts to their Wayfare trip pages. Use when the user runs /wayfare:fares or asks Wayfare to look for price drops on their flights.
---

# Wayfare fare check

Read `${CLAUDE_PLUGIN_ROOT}/reference/dashboard-io.md` first. `$P` means
`${CLAUDE_PLUGIN_ROOT}`.

Explain these limits the first time, in short plain words:
- It needs the user's own Duffel account and token in the environment
  variable `DUFFEL_ACCESS_TOKEN`. A test token (`duffel_test_...`) only shows
  Duffel's fake airline, so real flights never match.
- Cloud sessions usually cannot reach outside APIs. It works best in Claude
  Code on the user's own computer.
- Duffel prices can differ from the airline's own site, and whether a lower
  fare gives money back depends on the fare rules. Wayfare only alerts. It
  never changes or rebooks anything.
- Duffel may charge $0.005 per search above 1500 searches per booking made
  through Duffel. Each run makes at most 10 searches by default.

## Steps

1. dashboard-io.md sections A and B.
2. Run:

   ```bash
   python3 "$P/scripts/fare_check.py" \
     --bookings wayfare-work/db/home/private/bookings.json \
     --out wayfare-work/fares.json --max-searches 10
   ```

   If it reports an error (no token, network blocked), tell the user the
   error and stop. When this runs from a page request, put the error in the
   request status instead.
3. Save the results on Wayfare Home: `ArtifactData` `set` `private`/`fares`,
   `data: {"results": <contents of wayfare-work/fares.json>, "checkedAt":
   "<now ISO UTC>"}` (pass `if_version` if it exists). Copy that same object
   to `wayfare-work/db/home/private/fares.json`.
4. Copy `wayfare-work/db/home/private/bookings.json` to
   `wayfare-work/bookings.json`, then do sections C, E and F (no new pages
   are expected; if the plan lists new trips, do D as well).
5. Report: flights checked, any drop at or above the user's minimum, and
   what to do: open the booking on the airline's site and check the price
   or change policy for that fare.
