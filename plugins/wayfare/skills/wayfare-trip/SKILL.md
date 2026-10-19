---
name: wayfare-trip
description: Make the current chat the chat of one Wayfare trip. A scheduled task in this chat checks the trip every day and brings changes here, and the user can ask questions or add plans here. Use when the user asks to use this chat for a trip, for example "$wayfare-trip Lisbon".
---

# Wayfare trip chat

Read `../../reference/sites-io.md` (relative to this file).

## A. Connect this chat to a trip

1. Find the trip in `$WF/sites/home/worker/data.js` (`index.trips`) by
   city, title or slug. If several match, ask which one.
2. Create a scheduled task **in this chat** (it returns to this chat and
   keeps its context), named `Wayfare trip: <pageTitle>`, daily at about
   08:00 in the user's time zone, until 2 days after the trip ends, with the
   prompt: `$wayfare-check watch` for this trip's flights, then: "Tell me in
   one or two lines only what changed for <pageTitle> since your last
   message here, with the most useful next step; say nothing if nothing
   changed."
3. Tell the user in two short lines: this chat is now the chat for
   <pageTitle>, with the Site link from `$WF/sites/urls.json`; updates arrive
   here, and they can ask anything or add plans here.

## B. The user asks something in this chat

First read `$WF/changes.json`; start with changes for this trip that you
have not mentioned in this chat yet.

- **Add a plan** ("dinner at Cervejaria Ramiro on Saturday at 20:00"): write
  one booking object per data-model.md with `"source": "manual"` and an id
  that starts with `manual-`, confirm the facts in one line, merge it
  (`wayfare.py merge --new`), build and redeploy the trip Site.
- **Change or remove a manual item**: same flow; a removed item gets
  `"status": "cancelled"`. Never change bookings from email; tell the user to
  change those with the provider.
- **Find something** (stays, a restaurant near the hotel, the way from the
  airport): use web search and give links to the provider. Wayfare never
  books or pays.
- **Packing or tips**: `../wayfare-guide/SKILL.md`.
