---
name: wayfare-setup
description: Set up Wayfare, the open-source travel agent, in ChatGPT or Codex. Creates the Wayfare folder, saves the travel profile, checks the Gmail and Sites plugins, runs the first inbox sync (one ChatGPT Site per trip plus Wayfare Home) or loads sample trips, and creates the daily and new-email scheduled tasks. Use when the user asks to set up, repair or reset Wayfare.
---

# Wayfare setup

Wayfare reads travel confirmations from the user's Gmail and gives each trip
its own ChatGPT Site: day by day with weather, problems to check (nights
with no stay, tight connections, schedule changes, live delays), a Good to
know tab, a shared to-do list and a calendar file. Wayfare never books,
cancels or pays.

Read `../../reference/sites-io.md` (relative to this file) first. Tell the
user in one sentence what setup does and that it takes a few minutes.

## 1. The Wayfare folder

Use the current project if it has a `wayfare.json`. Otherwise propose
`~/Wayfare` (one question) and create it with `wayfare.json`:
`{"version": 1, "ownerEmail": null, "homeUrl": null}`, and empty `guides/`
and `sites/` folders. Scheduled tasks will run in this folder, so tell the
user to open it as a project in the ChatGPT desktop app if it is not.

## 2. Owner email and profile

Ask in ONE message:
- the email of their ChatGPT account (the Sites use it to know the owner);
- home airport code(s) and home city, for example "AMS, Amsterdam";
- anything Wayfare should know about how they like to fly, stay and eat.

Then ask (defaults are fine): minimum time to change flights (75 min),
minimum time from landing to a dinner booking (150 min), smallest fare drop
worth an alert per traveller (25), and whether to check fares (needs a
SearchApi key, `../../reference/keys.md`).

Write `ownerEmail` into `wayfare.json` and the profile (data-model.md,
`../../reference/data-model.md`) into `$WF/profile.json`.

## 3. Plugins

- **Gmail**: check that the Gmail plugin is installed and connected. If not,
  ask the user to add it from the Plugins directory and connect their
  account. Wayfare only opens emails that look like bookings.
- **Sites**: check that `@Sites` is available. If not, say that Sites needs
  a Plus, Pro or eligible workspace plan and may not be available in every
  region; Wayfare can still build the trip pages for local preview.

## 4. First trips

Ask which they want:
- **Sync my inbox now** (default): follow `../wayfare-sync/SKILL.md`.
- **Show sample trips first**: copy each `$P/samples/guide.<slug>.sample.json`
  to `$WF/guides/<slug>.json`, then run site-bundle (sites-io.md) with
  `--bookings "$P/samples/bookings.sample.json" --profile "$P/samples/profile.sample.json"
  --fares "$P/samples/fares.sample.json" --sample`, and publish as in
  sites-io.md. Sample Sites show a "Sample trip" banner and never touch
  `bookings.json`; at the first real sync they stop updating.

## 5. Scheduled tasks

Create, in the `$WF` project (sites-io.md, "Scheduled tasks"):
1. **Wayfare daily check**, daily at about 07:45 in the user's time zone.
2. **Wayfare new booking email**, started by new Gmail messages, if their
   plan supports app-event tasks. If not, say the daily check covers it.

Each run uses some of their usage. The tasks need the computer on and the
app running.

## 6. Finish

In three short lines: Wayfare Home and each trip are ChatGPT Sites (they
open on the phone too); share a trip from its Site's **Share** menu with
named people (they see the trip but never full booking codes or prices, and
they sign in with ChatGPT to tick to-dos); and for each trip they can start a
chat and use `$wayfare-trip <city>` to keep that trip's updates and
questions in one place.
