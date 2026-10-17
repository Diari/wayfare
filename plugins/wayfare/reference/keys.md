# Optional live data

All optional. Wayfare works without them.

| What | Service | Key |
|------|---------|-----|
| Weather | Open-Meteo (`api.open-meteo.com`, `geocoding-api.open-meteo.com`, `archive-api.open-meteo.com`) | none, free |
| Flight status | Aviationstack (`api.aviationstack.com`) | `AVIATIONSTACK_ACCESS_KEY` (100 free requests a month) |
| Live fares and stay prices | SearchApi, Google Flights and Google Hotels engines (`www.searchapi.io`) | `SEARCHAPI_API_KEY` (100 free searches, then about $4 per 1,000) |
| Status without a key | the public Flightradar24 page, read with web search or browsing | none |

Scheduled tasks in the ChatGPT desktop app run on the user's computer, so
they reach these services directly. Put keys in the environment of the app
(for example in the shell profile the app uses, or a `.env` file in `$WF`
that the skills load with `set -a; . "$WF/.env"; set +a`). Never put a key
in a chat, in `wayfare.json`, or in a Site.
