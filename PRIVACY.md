# Wayfare privacy policy

Last updated: 17 October 2026

Wayfare is an open-source plugin for Claude (Anthropic) and for ChatGPT and
Codex (OpenAI). It runs inside your own AI assistant account. **The Wayfare
authors keep none of your data.** The Claude plugin uses no Wayfare server.
The ChatGPT and Codex plugin calls the Wayfare MCP server, which stores
nothing (see below).

## What Wayfare reads

- **Your Gmail**, through the Gmail connector or plugin that you connect
  yourself. Wayfare first looks only at the sender, subject and short preview
  of emails. It opens the full text only of emails that look like travel
  bookings, schedule changes or cancellations (flights, trains, stays,
  restaurant tables). It ignores personal mail.
- **Your travel profile**: home airport and city, and preferences you type in.

## What Wayfare stores, and where

Only booking facts: names of places and providers, dates and times, booking
codes, prices, number of travellers, and a "manage booking" link. It never
stores email text.

- **Claude**: in the database of artifacts (pages) in your own Claude account:
  a private "Wayfare Home" page and one page per trip. Full booking codes,
  prices and manage links are in an owner-only part of each page.
- **ChatGPT and Codex**: in a folder on your computer that you choose, and in
  ChatGPT Sites in your own account (one per trip). Full booking codes and
  manage links are served by a Site only to its owner.

You decide who sees a trip page or Site, with its own **Share** menu. People
you share with see the trip plan, but never full booking codes, prices or
manage links. What they add on the page (to-dos, "handled" marks) is stored in
that page. Each person's packing ticks are visible only to that person.

To delete your data, delete the Wayfare pages or Sites, and the Wayfare
folder on your computer. Uninstalling the plugin stops all reading.

## The Wayfare MCP server (ChatGPT and Codex only)

The ChatGPT and Codex plugin connects to the Wayfare MCP server, a small web
service that the Wayfare publisher runs on Cloudflare Workers (the code is in
`mcp-server/` in the repository). It has three read-only tools: check a trip
plan, get the trip weather, and make a packing list.

- **What it receives**: the trip facts in the tool request: places, dates and
  times, flight numbers, hotel and restaurant names, home airport or city.
  It drops every other field (for example booking codes, prices or links)
  before it uses the request. Do not send names of people or email text.
- **What it keeps**: nothing. It has no database and no sign-in, and request
  logging is turned off. Each request is handled and then forgotten.
- **Who else sees it**: Cloudflare carries the request (see Cloudflare's
  privacy policy). For weather, the server sends the city name, its
  coordinates and the dates to Open-Meteo.

## Services Wayfare contacts

All optional except your assistant and Gmail. Wayfare sends each service only
what is needed:

| Service | What it receives | When |
|---------|------------------|------|
| Wayfare MCP server (Cloudflare Workers) | trip facts listed above, nothing stored | ChatGPT and Codex tools |
| Open-Meteo (`open-meteo.com`) | city names, coordinates and trip dates | weather |
| Aviationstack (`aviationstack.com`) | your flight number | live flight status, Codex plugin only, with your key |
| Flightradar24 (`flightradar24.com`) | your flight number (a public page is read) | live flight status without a key |
| SearchApi (`searchapi.io`) | airports, dates, cabin, number of travellers; hotel name, city, dates, number of guests | fare and stay price checks, only with your key |
| Duffel (`duffel.com`) | airports, dates, cabin, number of travellers | fare checks, only if you choose Duffel and add your key |
| Web search | city names and travel questions | the "Good to know" tab and stay suggestions |
| GitHub (`github.com/Diari/wayfare`) | nothing personal; the plugin code is downloaded | Claude scheduled runs, where installed plugins are not loaded |
| Google Calendar | trip events | only when you select "Add trip to my calendar" (Claude) |

Wayfare never sends your booking codes, prices, names or email content to any
of these services. Links on the pages (maps, provider sites, Google Hotels,
Booking.com searches) open only when you select them.

API keys stay in your own environment settings. Wayfare never asks you to
paste a key into a chat or a page.

## Children

Wayfare is not intended for people under 18.

## Changes and contact

Changes to this policy are published in this file, with the date above.
Questions: open an issue at https://github.com/Diari/wayfare/issues.
