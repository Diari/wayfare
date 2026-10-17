---
name: wayfare-sync
description: Read new travel confirmations, schedule changes and cancellations from the user's Gmail and update Wayfare - one ChatGPT Site per trip with unbooked nights, tight connections, schedule-change effects and other alerts, plus Wayfare Home. Use when the user asks to sync, update or refresh their trips, or forwards a new booking.
---

# Wayfare sync

Read `../../reference/sites-io.md` and `../../reference/data-model.md`
(relative to this file) first. Follow the safety rules there.

1. **Window.** If `$WF/wayfare.json` has `lastSync`, search from 2 days
   before it (`after:YYYY/MM/DD`). Otherwise `newer_than:180d`.

2. **Pass 1, headers only.** With the Gmail plugin, search (sender, subject
   and snippet only, up to 150 results per query, window added to each):
   - `category:reservations`
   - `subject:(confirmation OR confirmed OR itinerary OR booking OR reservation OR e-ticket OR "schedule change" OR "flight change" OR "time change" OR cancelled OR cancellation) -category:promotions -category:social`
   - `from:(booking.com OR airbnb OR opentable OR resy OR thefork OR expedia OR hotels.com OR trainline OR ns.nl OR bahn OR eurostar)`

   Keep a thread only if sender and subject show a real booking, change or
   cancellation for travel: flight, train, coach, ferry, stay, restaurant
   table, car or transfer. Drop sales, newsletters, check-in reminders
   without new facts, and all personal mail.

3. **Pass 2, kept threads only.** Read each kept email as plain text. Write
   one booking object per flight leg, train, stay or table, exactly as
   data-model.md says (ids, local times with the place's UTC offset, total
   price, travellers). Add `manageUrl` only for an `https://` "manage
   booking" link on the sender's own domain. For a stay, set `refundable` (true when the email says
   "free cancellation" or "refundable") and `freeCancelUntil` (the last
   moment you can cancel for free, ISO with offset, or a date) when the
   email gives it. For a change or cancellation,
   use the same `confirmation` with the new facts or `status: "cancelled"`.
   Skip facts you are not sure about. Save the list to `$WF/new.json`.

4. **Merge.**

   ```bash
   python3 "$P/scripts/wayfare.py" merge --existing "$WF/bookings.json" \
     --new "$WF/new.json" --out "$WF/bookings.json"
   ```

   (With no new emails, keep `bookings.json` and still rebuild: alerts depend
   on today.) Then set `lastSync` in `$WF/wayfare.json` to now (ISO, UTC).

5. **Build and publish**: sites-io.md, "Build the Sites" and "Publish with
   Sites". New trips get a new Site; trips that grow keep their Site; a trip
   whose bookings were all cancelled shows a "cancelled" banner.

6. **Report**: sites-io.md, "Report", and how many emails were checked and
   ignored.
