---
name: fares
description: Optional and experimental. Check whether the same flights the user already booked now sell for less, using the user's own Duffel API token, and add fare-drop alerts to the Wayfare Trips dashboard. Use when the user runs /wayfare:fares or asks Wayfare to look for price drops on their flights.
---

# Wayfare fare check

Read `${CLAUDE_PLUGIN_ROOT}/reference/dashboard-io.md` first. `$P` means
`${CLAUDE_PLUGIN_ROOT}`.

Explain these limits to the user the first time, in short plain words:
- It needs the user's own Duffel account and token in the environment
  variable `DUFFEL_ACCESS_TOKEN`. A test token (`duffel_test_...`) only shows
  Duffel's fake airline, so real flights never match.
- Cloud sessions often cannot reach outside APIs. It works best in Claude
  Code on the user's own computer.
- Duffel prices can differ from the airline's own site, and whether a lower
  fare gives money back depends on the fare rules. Wayfare only alerts. It
  never changes or rebooks anything.
- Duffel may charge $0.005 per search above 1500 searches per booking made
  through Duffel. Each run makes at most 10 searches by default.

## Steps

1. Dashboard sections A and B.
2. Run:

   ```bash
   python3 "$P/scripts/fare_check.py" \
     --bookings wayfare-work/db/private/bookings.json \
     --out wayfare-work/fares.json --max-searches 10
   ```

   If it reports an error (no token, network blocked), tell the user the
   error and stop.
3. Save the results owner-only: `ArtifactData` `set`, `collection:
   "private"`, `doc_id: "fares"`, `data: {"results": <contents of
   wayfare-work/fares.json>, "checkedAt": "<now, ISO UTC>"}` (pass
   `if_version` if the document exists).
4. Copy `wayfare-work/db/private/bookings.json` to
   `wayfare-work/bookings.json`, then build with
   `--fares wayfare-work/fares.json` and write (sections C and D).
5. Report: flights checked, any drop at or above the user's minimum, and
   what to do: open the booking on the airline's site and check the change
   or price-drop policy for that fare.
