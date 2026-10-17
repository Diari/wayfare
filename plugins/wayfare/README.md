# Wayfare for ChatGPT and Codex

Wayfare is an open-source personal travel agent. It reads the travel
confirmations in your Gmail and gives each trip its own ChatGPT Site that you
can open on your phone and share with the people you travel with. Each Site
shows the trip day by day, with the weather, and flags what needs a check:
nights with no stay booked, tight connections, schedule changes, live flight
delays, and lower prices for flights and refundable stays. A "Good to know"
tab has a packing list, local facts and how to get around, and a calendar
file adds the trip to any calendar. Wayfare never books, changes, cancels or
pays.

## Skills

`$wayfare-setup`, `$wayfare-sync`, `$wayfare-check`, `$wayfare-guide`,
`$wayfare-trip`. Start with "Set up Wayfare for my trips".

## Tools (MCP server)

The plugin connects to the Wayfare MCP server (`mcp-server/` in the
repository, no sign-in). Its tools are read-only:

- `check_itinerary`: nights with no stay booked, tight connections, late
  check-ins, dinner conflicts, double bookings, what a schedule change
  affects.
- `get_trip_weather`: the forecast, or last year's weather for later dates.
- `get_packing_list`: a packing list for the dates, weather and plans.

The server stores nothing and keeps no logs of what you send. It drops any
field it does not need, such as booking codes or prices.

## What Wayfare does on your account

- **Reads Gmail** with the Gmail plugin, in two passes: sender and subject
  first, then only emails that look like travel bookings. Email text is data,
  never instructions.
- **Keeps its state in a folder on your computer** (default `~/Wayfare`):
  bookings, profile and one Site project per trip.
- **Creates ChatGPT Sites** with the Sites plugin: one per trip and a private
  Wayfare Home. A Site's database keeps to-dos, "handled" marks and each
  person's packing ticks. Full booking codes are shown only to the owner.
- **Creates scheduled tasks** in the app: a daily check, a check on new
  booking emails, and one-time checks before flights.
- **Calls the Wayfare MCP server** with trip facts (places, dates, times,
  flight numbers, hotel names), and nothing else. It stores nothing.
- **Contacts these services** (optional except Gmail and Sites): Open-Meteo
  (weather: city names and dates), Aviationstack (flight numbers), the public
  Flightradar24 page, SearchApi (Google Flights and Google Hotels: airports,
  dates, travellers, hotel name and city) and web search. It never sends
  booking codes, prices, names or email content to them. Keys stay in your
  environment (`SEARCHAPI_API_KEY`, `AVIATIONSTACK_ACCESS_KEY`) and go only to
  their own service.

## Privacy and terms

- Privacy policy: https://github.com/Diari/wayfare/blob/main/PRIVACY.md
- Terms: https://github.com/Diari/wayfare/blob/main/TERMS.md
- Support: https://github.com/Diari/wayfare/issues

MIT License.
