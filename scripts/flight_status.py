#!/usr/bin/env python3
"""Wayfare flight status (optional).

Gets the live status of your booked flights from Aviationstack
(https://aviationstack.com): delay, new times, cancellation, terminal, gate
and baggage belt. It reads only; it never changes a booking.

Key: put your Aviationstack access key in AVIATIONSTACK_ACCESS_KEY.
Aviationstack takes the key as a URL parameter (access_key=...), so an
"API credential" that adds a header does not work for it; use an environment
variable on the cloud environment and allow api.aviationstack.com.

Limits you should know:
  * The free plan has 100 requests a month. Wayfare checks only flights that
    leave in the next --window-hours (default 30) and skips flights checked in
    the last --min-age-minutes (default 90).
  * Real-time data covers flights of about today and tomorrow. Future dates
    are a paid feature, so a check days before the flight finds nothing.
  * Aviationstack writes LOCAL airport times with a "+00:00" offset. This
    script keeps only the wall-clock part ("2026-11-06T16:55").

Output: a JSON list of status records that `wayfare.py build --status` reads.
The same shape can be written by hand from a public flight page (see
skills/watch/SKILL.md) when no key is set.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.aviationstack.com/v1/flights"
STATES = {"scheduled", "active", "landed", "cancelled", "incident", "diverted"}


def wall(v: str | None) -> str | None:
    """'2026-11-06T16:55:00+00:00' -> '2026-11-06T16:55'."""
    return v[:16] if isinstance(v, str) and len(v) >= 16 else None


def candidates(bookings: list[dict], previous: dict[str, dict], now: datetime,
               window_hours: float, min_age_minutes: float) -> tuple[list[dict], list[dict]]:
    check, skipped = [], []
    for b in bookings:
        if b.get("type") != "flight" or b.get("status") == "cancelled":
            continue
        try:
            dep, arr = datetime.fromisoformat(b["depart"]), datetime.fromisoformat(b["arrive"])
        except (KeyError, ValueError):
            continue
        if arr < now - timedelta(hours=2) or dep > now + timedelta(hours=window_hours):
            continue
        if not b.get("carrier") or not b.get("flightNumber"):
            skipped.append({"bookingId": b["id"], "reason": "no flight number"})
            continue
        prev = previous.get(b["id"])
        if prev:
            try:
                age = (now - datetime.fromisoformat(prev["checkedAt"].replace("Z", "+00:00"))).total_seconds() / 60
            except (KeyError, ValueError):
                age = 1e9
            if age < min_age_minutes:
                skipped.append({"bookingId": b["id"], "reason": f"checked {age:.0f} min ago"})
                continue
        check.append(b)
    return check, skipped


def pick(b: dict, data: list[dict]) -> dict | None:
    """The record for the booked day and departure airport."""
    day = b["depart"][:10]
    for f in data or []:
        dep = f.get("departure") or {}
        if f.get("flight_date") == day and (dep.get("iata") or "").upper() == (b.get("from") or "").upper():
            return f
    for f in data or []:
        if f.get("flight_date") == day:
            return f
    return None


def normalise(b: dict, f: dict, now: datetime) -> dict:
    dep, arr = f.get("departure") or {}, f.get("arrival") or {}
    state = f.get("flight_status") if f.get("flight_status") in STATES else "scheduled"
    return {
        "bookingId": b["id"], "flight": f"{b['carrier']} {b['flightNumber']}", "flightDate": f.get("flight_date"),
        "state": state,
        "depScheduled": wall(dep.get("scheduled")), "depEstimated": wall(dep.get("estimated")), "depActual": wall(dep.get("actual")),
        "arrScheduled": wall(arr.get("scheduled")), "arrEstimated": wall(arr.get("estimated")), "arrActual": wall(arr.get("actual")),
        "depDelay": dep.get("delay"), "arrDelay": arr.get("delay"),
        "depTerminal": dep.get("terminal"), "depGate": dep.get("gate"),
        "arrTerminal": arr.get("terminal"), "arrGate": arr.get("gate"), "baggage": arr.get("baggage"),
        "checkedAt": now.isoformat(timespec="seconds"), "source": "Aviationstack",
    }


def get(params: dict, timeout: float = 30.0) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
        return json.loads(r.read().decode())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bookings", required=True)
    p.add_argument("--previous", help="earlier status list (kept and updated)")
    p.add_argument("--out", required=True)
    p.add_argument("--window-hours", type=float, default=30)
    p.add_argument("--min-age-minutes", type=float, default=90)
    p.add_argument("--max-requests", type=int, default=6)
    p.add_argument("--pause-seconds", type=float, default=2)
    a = p.parse_args(argv)

    key = os.environ.get("AVIATIONSTACK_ACCESS_KEY", "").strip()
    data = json.loads(Path(a.bookings).read_text(encoding="utf-8"))
    bookings = data["bookings"] if isinstance(data, dict) else data
    prev_list = []
    if a.previous and Path(a.previous).exists() and Path(a.previous).read_text().strip():
        prev_list = json.loads(Path(a.previous).read_text(encoding="utf-8"))
        prev_list = prev_list.get("results", prev_list) if isinstance(prev_list, dict) else prev_list
    previous = {r["bookingId"]: r for r in prev_list}
    now = datetime.now(timezone.utc)
    check, skipped = candidates(bookings, previous, now, a.window_hours, a.min_age_minutes)
    report = {"checked": [], "skipped": skipped, "requests": 0, "error": None}

    if check and not key:
        report["error"] = ("AVIATIONSTACK_ACCESS_KEY is not set. Live status is off; the watch skill can read a "
                           "public flight page instead.")
    elif check:
        for i, b in enumerate(check[: a.max_requests]):
            if i:
                time.sleep(a.pause_seconds)
            try:
                resp = get({"access_key": key, "flight_iata": f"{b['carrier']}{b['flightNumber']}"})
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:300]
                report["error"] = f"Aviationstack returned HTTP {e.code}: {body}"
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                report["error"] = (f"Cannot reach api.aviationstack.com ({e}). In a cloud session, allow "
                                   "api.aviationstack.com in the environment's network access.")
                break
            report["requests"] += 1
            if resp.get("error"):
                report["error"] = f"Aviationstack error: {resp['error'].get('code')}: {resp['error'].get('message')}"
                break
            f = pick(b, resp.get("data") or [])
            if not f:
                report["checked"].append({"bookingId": b["id"], "result": "no record for that day yet"})
                continue
            rec = normalise(b, f, now)
            previous[b["id"]] = rec
            report["checked"].append({"bookingId": b["id"], "result": rec["state"],
                                      "depDelay": rec["depDelay"], "gate": rec["depGate"]})
        if len(check) > a.max_requests:
            report["skipped"] += [{"bookingId": b["id"], "reason": "over --max-requests"} for b in check[a.max_requests:]]

    # Keep only records for flights that are not long past.
    ids = {b["id"]: b for b in bookings}
    keep = []
    for r in previous.values():
        b = ids.get(r["bookingId"])
        if b and datetime.fromisoformat(b["arrive"]) > now - timedelta(days=2):
            keep.append(r)
    Path(a.out).write_text(json.dumps(keep, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
