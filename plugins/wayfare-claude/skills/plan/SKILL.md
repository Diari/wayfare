---
name: plan
description: Plan a trip the user has NOT booked yet. Turn their own words (where, why, dates, who travels, flight times, stay wishes) into a Wayfare plan, ask only for what is missing, search live flight and hotel prices (Google Flights and Google Hotels via SearchApi), publish a plan page, and keep watching the prices so the daily check can alert when they drop. Use when the user runs /wayfare:plan, describes a trip they want to take, asks Wayfare to find flights and hotels, or asks to change, pause or stop a plan.
---

# Wayfare plan

A plan is a trip that is not booked yet. Wayfare finds the best matching
flights and stays, shows them on a plan page, and re-checks the prices in the
daily check ("scanner"). It never books or pays: the user books on the
airline or hotel site. When the booking emails arrive, the sync marks those
parts as booked and the trip gets its normal trip page.

Read `${CLAUDE_PLUGIN_ROOT}/reference/dashboard-io.md` (sections A, B, K and
J) and the "Plan object" in `${CLAUDE_PLUGIN_ROOT}/reference/data-model.md`.
`$P` means `${CLAUDE_PLUGIN_ROOT}`. Work in `wayfare-work`.

## 1. Understand the trip

Read Home (dashboard-io.md A and K.1): the profile (home airports, home city,
currency, stay style) and the existing plans. If the user asks to change,
pause, resume or stop a plan, edit that plan (status `paused`, `watching` or
`ended`) and go to step 4.

From the user's words, fill in as much of the plan object as you can. Example:
"Wedding in Teulada, Spain. Recommended to stay at Pueblo Mascarat. Flying
AMS to Alicante Thu 10 June 2027, back Sunday 13 June. 2 adults, 2 kids 5
and 3. 4-star hotel or more. Fly Thursday morning, be back in AMS by 6pm."
gives:

- `title` "Wedding in Teulada", `purpose` "wedding", `destination` Teulada, Spain;
- `travellers` `{"adults": 2, "childrenAges": [5, 3]}`;
- `flights.out` AMS → ALC on 2027-06-10, `departAfter` "06:00",
  `departBefore` "12:00" ("morning");
- `flights.back` ALC → AMS on 2027-06-13, `arriveBefore` "18:00";
- `stay` 2027-06-10 to 2027-06-13, `near` "Pueblo Mascarat, Altea",
  `minStars` 4, `preferred` ["Pueblo Mascarat"].

Rules:
- Words for times: early morning 05:00–09:00, morning 06:00–12:00,
  afternoon 12:00–18:00, evening 17:00–23:00. "Back by 6pm" on the return
  is `arriveBefore` "18:00"; on the way out, "arrive by" is `arriveBefore`.
- Check that each date is the weekday the user said. If not, ask.
- Airports: use IATA codes. If the user named a city, pick its main airport
  and the nearest other airport worth checking (at most 2 per side; each
  extra airport is one more search). Say which airports you chose.
- `near` must be a place the hotel search can find (add the town: "Pueblo
  Mascarat, Altea"). If you know the place's coordinates, put them in
  `nearLat`/`nearLon`; otherwise the search looks them up.
- Children: keep their ages. Under 2 travel on a lap; 2 to 11 are children;
  12 and over pay as adults (the planner does this).
- Use the profile's currency (default EUR) and home airports.

## 2. Ask only what is missing

Ask at most 4 short questions, in ONE `AskUserQuestion` call when available
(otherwise one plain message), and only about facts that change the search.
Put the most likely answer first and mark it "(Recommended)". Typical:

- **Direct only?** Direct only (Recommended when direct flights exist) / One stop is fine.
- **Rooms:** One family room / Two rooms. (Google Hotels prices one room
  for all guests; with two rooms, say the price is for one room and set `rooms`.)
- **Free cancellation only?** Yes (Recommended: then you can rebook when the
  price drops) / No.
- **How far from the place?** Within 10 km / 20 km (Recommended) / Any distance.
- Hotel or apartment, checked bags, a budget, a missing date or traveller.

Do not ask what the user already said. Do not ask about anything that the
search cannot use. If the user says "you decide", use the recommended answers
and say so.

## 3. Confirm

Show a short summary (5 to 8 lines): who, where, dates, flight wishes per leg
with airports, stay wishes, and "Wayfare checks prices every day (every 3
days while the trip is more than 2 months away) and tells you when they drop.
It never books." Ask "Shall I start?" unless the user already asked you to go
ahead. Then write the plan:

- `id`: lowercase place + year + month, for example `teulada-2027-06`
  (add `-2` if it exists).
- `status` `watching`.

Validate it:

```bash
python3 "$P/scripts/planner.py" validate --plans wayfare-work/plans.json
```

## 4. Search, build and publish

dashboard-io.md section K, steps 2 to 6, with `--plan <id> --every-hours 0`
for the search. If SearchApi is not set up (the search reports a key or
network error): still build and publish the plan page; it shows the wishes
and links to Google Flights, Google Hotels and Booking.com, with no prices.
Tell the user how to add the key (dashboard-io.md J) and that the daily
check starts watching once it works.

## 5. Report

In a few lines: the cheapest matching flight for each leg (time, airline,
price for all travellers), the cheapest matching stays (name, stars, price
for all nights), the estimated total, and anything that did not match (for
example "no direct flight back arrives by 18:00; the first one lands at
18:40"). Then: "I check the prices every day and tell you when they drop.
Book on the airline or hotel site when you are ready; Wayfare picks up the
booking from your email." Do not paste the whole page.

If the daily check task does not exist (Home `private`/`agent` has no
`dailyTriggerId`), offer to set it up (`$P/skills/setup/SKILL.md` step 4),
because the scanner runs in the daily check.

Never book, reserve, pay, or enter personal details on any site.
