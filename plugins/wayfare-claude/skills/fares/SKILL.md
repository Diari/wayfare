---
name: fares
description: Optional. Check whether the same flights the user already booked now sell for less, with Google Flights prices through the user's own SearchApi key (or Duffel), and add fare-drop alerts to their Wayfare trip pages. Use when the user runs /wayfare:fares or asks Wayfare to look for price drops on their flights.
---

# Wayfare fare check

Read `${CLAUDE_PLUGIN_ROOT}/reference/dashboard-io.md` first. `$P` means
`${CLAUDE_PLUGIN_ROOT}`.

Explain these limits the first time, in short plain words:
- It needs the user's own SearchApi key (www.searchapi.io; 100 free
  searches, then about $4 per 1,000), added as an **API credential** for
  `www.searchapi.io` on the cloud environment (dashboard-io.md J), so the
  key never reaches Claude. Wayfare never reads keys from the user's machine.
- The price is today's public Google Flights price for the same flight and
  cabin. Whether a lower fare gives money back depends on the fare rules.
  Wayfare only alerts. It never changes or rebooks anything.
- Each flight is checked at most every 3 days, at most 6 searches a run.
- Duffel works too (`--provider duffel`), with an API credential for
  `api.duffel.com`.

## Steps

1. dashboard-io.md sections A and B.
2. Run:

   ```bash
   python3 "$P/scripts/fare_check.py" --provider searchapi \
     --bookings wayfare-work/db/home/private/bookings.json \
     --previous wayfare-work/db/home/private/fares.json \
     --out wayfare-work/fares.json --every-days 3 --max-searches 6
   python3 "$P/scripts/stay_check.py" \
     --bookings wayfare-work/db/home/private/bookings.json \
     --previous wayfare-work/fares.json --out wayfare-work/fares.json --every-days 2 --max-stays 4
   ```

   The second command checks refundable stays: the cheapest offer for the
   same hotel, dates and guests that also has free cancellation (Google
   Hotels via SearchApi). Only stays with `refundable: true` whose free
   cancellation has not ended are checked.

   Add `--every-days 0` when the user asked for a check right now. If it
   reports an error (no key, network blocked), tell the user the error and
   what to set (dashboard-io.md J), and stop. When this runs from a page request, put the error in the
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
