# Wayfare MCP server

A small [MCP](https://modelcontextprotocol.io) server for the Wayfare
ChatGPT and Codex plugin. MCP (Model Context Protocol) is the standard way
for an AI assistant to call tools on a web service.

- Endpoint: `POST /mcp` (Streamable HTTP, JSON answers). No sign-in.
- Tools, all read-only:
  - `check_itinerary`: nights with no stay booked, tight or impossible
    connections, late check-ins and no-show risk, dinner conflicts, double
    bookings, and what a schedule change affects. The same rules as
    `plugins/wayfare-claude/scripts/wayfare.py` (a test checks this).
  - `get_trip_weather`: Open-Meteo forecast for the next 16 days, and the
    weather on the same dates last year for later dates.
  - `get_packing_list`: a packing list from the dates, weather and plans.
- Stores nothing: no database, no request logs. It drops booking fields it
  does not need (codes, prices, links). It never books or pays.

## Deploy (Cloudflare Workers, free plan)

```bash
cd mcp-server
npm install
npx wrangler login        # opens Cloudflare in your browser
npx wrangler deploy       # prints https://wayfare-mcp.<your-subdomain>.workers.dev
```

Then, in the repository root:

```bash
python3 tools/set_mcp_url.py https://wayfare-mcp.<your-subdomain>.workers.dev/mcp
python3 tools/validate_codex.py && python3 tools/build_codex_zip.py
```

OpenAI's domain check gives you a token. Store it as a secret (it is never
in the code), then select **Verify** in the OpenAI dashboard:

```bash
npx wrangler secret put OPENAI_APPS_CHALLENGE
```

The server then returns the token at
`/.well-known/openai-apps-challenge`.

## Test

```bash
npm test                  # unit tests, and the same results as the Python engine
npx wrangler dev          # local server on http://localhost:8787/mcp
```
