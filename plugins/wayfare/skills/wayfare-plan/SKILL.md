---
name: wayfare-plan
description: Plan a trip the user has NOT booked yet. Turn their own words (where, why, dates, who travels, flight times, stay wishes) into a Wayfare plan, ask only for what is missing, search live flight and hotel prices (Google Flights and Google Hotels via SearchApi), publish a plan Site, and keep watching the prices so the daily check alerts when they drop. Use when the user describes a trip they want to take, asks Wayfare to find flights and hotels, or asks to change, pause or stop a plan.
---

# Wayfare plan

A plan is a trip that is not booked yet. Wayfare finds the best matching
flights and stays, shows them on a plan Site, and re-checks the prices in
the daily check ("scanner"). It never books or pays: the user books on the
airline or hotel site. When the booking emails arrive, the sync marks those
parts as booked.

Read `../../reference/sites-io.md` and the "Plan object" in
`../../reference/data-model.md`. Load keys if `$WF/.env` exists
(`set -a; . "$WF/.env"; set +a`, never print it). Plans are in
`$WF/plans.json` (`{"plans": [...]}`), prices in `$WF/planprices.json`.

## 1. Understand the trip

From the user's words, fill in as much of the plan object as you can, with
`$WF/profile.json` for home airports and currency. Example: "Wedding in
Teulada, Spain. Recommended to stay at Pueblo Mascarat. Flying AMS to
Alicante Thu 10 June 2027, back Sunday 13 June. 2 adults, 2 kids 5 and 3.
4-star hotel or more. Fly Thursday morning, be back in AMS by 6pm." gives
`travellers` `{"adults": 2, "childrenAges": [5, 3]}`; `flights.out` AMS → ALC
on 2027-06-10 with `departAfter` "06:00" and `departBefore` "12:00";
`flights.back` ALC → AMS on 2027-06-13 with `arriveBefore` "18:00"; `stay`
2027-06-10 to 2027-06-13 `near` "Pueblo Mascarat, Altea", `minStars` 4,
`preferred` ["Pueblo Mascarat"].

- Times: early morning 05:00–09:00, morning 06:00–12:00, afternoon
  12:00–18:00, evening 17:00–23:00. "Back by 6pm" is `arriveBefore` "18:00".
- Check that each date is the weekday the user said; if not, ask.
- IATA airport codes, at most 2 per side (each one is another search).
- `near` must be a place a hotel search finds (add the town).
- To change, pause (`paused`), resume (`watching`) or stop (`ended`) a plan,
  edit it in `$WF/plans.json` and go to step 4.

## 2. Ask only what is missing

At most 4 short questions, in one message, only about facts that change the
search, with a recommended answer: direct only?; one family room or two
rooms?; free cancellation only? (recommended: then the user can rebook when
the price drops); how far from the place (10 km / 20 km / any)? Do not ask
what the user already said. "You decide" means the recommended answers.

## 3. Confirm and save

Show a 5 to 8 line summary and "Wayfare checks prices every day (every 3
days while the trip is more than 2 months away) and tells you when they
drop. It never books." Then add the plan to `$WF/plans.json` with `id` like
`teulada-2027-06` and `status` `watching`, and run:

```bash
python3 "$P/scripts/planner.py" validate --plans "$WF/plans.json"
```

## 4. Search and publish

```bash
python3 "$P/scripts/planner.py" search --plans "$WF/plans.json" \
  --previous "$WF/planprices.json" --out "$WF/planprices.json" --plan <id> --every-hours 0
python3 "$P/scripts/planner.py" site-bundle --plans "$WF/plans.json" \
  --prices "$WF/planprices.json" --sites-dir "$WF/sites" --urls "$WF/sites/urls.json"
```

If the search reports that `SEARCHAPI_API_KEY` is missing, still build and
publish: the plan Site shows the wishes and links to Google Flights, Google
Hotels and Booking.com. Tell the user how to add the key
(`../../reference/keys.md`).

Publish with Sites as sites-io.md says, using `$WF/sites/plans-plan.json`
(Sites named `plan-<id>`). Then run the normal Wayfare `site-bundle`
(sites-io.md "Build the Sites") so Wayfare Home lists the plan, and redeploy
Home if it changed.

## 5. Report

The cheapest matching flight per leg (time, airline, price for all
travellers), the cheapest matching stays (name, stars, total), the estimated
total, and what did not match. Then: "I check the prices every day and tell
you when they drop. Book on the airline or hotel site when you are ready."

Never book, reserve, pay, or enter personal details on any site.
