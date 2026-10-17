#!/usr/bin/env python3
"""Wayfare stay price check (optional).

For each REFUNDABLE stay that can still be cancelled for free, looks up the
same hotel on Google Hotels through SearchApi (https://www.searchapi.io) and
finds the cheapest offer for the same dates and guests that ALSO has free
cancellation. It never books or cancels anything.

Keys: see keys.py.

Limits you should know:
  * Google Hotels shows the cheapest room of the hotel. Your room type can
    differ, so the alert says "check that it is the same room".
  * Two searches for a new stay (find the hotel, then its offers), one for a
    stay checked before. Each stay is checked at most every --every-days days.
  * Taxes: Google's total price for the stay is compared with the total you
    paid. Small differences can be fees.

Output: records with "kind": "stay" in the same results file as
fare_check.py (flight records are kept as they are); `wayfare.py build
--fares` reads them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import keys

SEARCHAPI = "https://www.searchapi.io/api/v1/search"
STOP = {"hotel", "the", "and", "&", "rooms", "room", "guesthouse", "guest", "house", "hostel", "apartments",
        "suites", "by", "de", "do", "da", "la", "le", "sample"}


def words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if w not in STOP}


def same_hotel(a: str, b: str) -> bool:
    """Loose name match: most distinctive words of the booked name appear in the result."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa) >= 0.6


def deadline(b: dict) -> datetime | None:
    v = b.get("freeCancelUntil")
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def candidates(bookings: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    check, skipped = [], []
    for b in bookings:
        if b.get("type") != "hotel" or b.get("status") == "cancelled":
            continue
        try:
            ci = date.fromisoformat(b["checkIn"])
        except (KeyError, ValueError):
            continue
        if ci <= now.date():
            continue
        reason = None
        if b.get("refundable") is not True:
            reason = "not refundable (or unknown)"
        elif not (b.get("price") or {}).get("amount"):
            reason = "no price paid found"
        elif deadline(b) and deadline(b) <= now:
            reason = "free cancellation has ended"
        if reason:
            skipped.append({"bookingId": b["id"], "reason": reason})
        else:
            check.append(b)
    return check, skipped


def get(params: dict, timeout: float = 60.0) -> dict:
    headers = {"Accept": "application/json"}
    key = keys.get("searchapi")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = SEARCHAPI + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode())


def base_params(b: dict) -> dict:
    return {"check_in_date": b["checkIn"], "check_out_date": b["checkOut"],
            "adults": max(1, min(6, int(b.get("travelers") or 2))),
            "currency": b["price"].get("currency") or "EUR", "hl": "en", "gl": "nl"}


def find_token(b: dict, resp: dict) -> str | None:
    for p in resp.get("properties") or []:
        if p.get("property_token") and same_hotel(b.get("name", ""), p.get("name", "")):
            return p["property_token"]
    return None


def best_free_cancel_offer(resp: dict) -> dict | None:
    prop = resp.get("property") or resp
    best = None
    for o in (prop.get("featured_offers") or []) + (prop.get("all_offers") or []):
        if not o.get("has_free_cancellation"):
            continue
        total = (o.get("total_price") or {}).get("extracted_price")
        if not isinstance(total, (int, float)) or total <= 0:
            continue
        if best is None or total < best["total"]:
            link = o.get("link") or o.get("tracking_link")
            fcu = o.get("free_cancellation_until") or {}
            best = {"total": float(total), "source": o.get("source") or "",
                    "link": link if isinstance(link, str) and link.startswith("https://") else None,
                    "freeCancelUntil": " ".join(x for x in (fcu.get("date"), fcu.get("time")) if x) or None}
    return best


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bookings", required=True)
    p.add_argument("--previous", help="earlier fare results (kept; stays checked recently are skipped)")
    p.add_argument("--out", required=True)
    p.add_argument("--every-days", type=float, default=2)
    p.add_argument("--max-stays", type=int, default=4)
    a = p.parse_args(argv)

    data = json.loads(Path(a.bookings).read_text(encoding="utf-8"))
    bookings = data["bookings"] if isinstance(data, dict) else data
    prev_list = []
    if a.previous and Path(a.previous).exists() and Path(a.previous).read_text().strip():
        prev_list = json.loads(Path(a.previous).read_text(encoding="utf-8"))
        prev_list = prev_list.get("results", prev_list) if isinstance(prev_list, dict) else prev_list
    previous = {r["bookingId"]: r for r in prev_list}
    now = datetime.now(timezone.utc)
    check, skipped = candidates(bookings, now)
    report = {"checked": [], "skipped": skipped, "searches": 0, "error": None}
    due = []
    for b in check:
        r = previous.get(b["id"])
        try:
            recent = r and now - datetime.fromisoformat(r["checkedAt"].replace("Z", "+00:00")) < timedelta(days=a.every_days)
        except (KeyError, ValueError):
            recent = False
        if recent:
            skipped.append({"bookingId": b["id"], "reason": f"checked in the last {a.every_days:g} days"})
        else:
            due.append(b)

    for b in due[: a.max_stays]:
        try:
            token = (previous.get(b["id"]) or {}).get("propertyToken")
            if not token:
                found = get({"engine": "google_hotels", "q": f"{b['name']}, {b.get('city', '')}", **base_params(b)})
                report["searches"] += 1
                token = find_token(b, found)
                if not token:
                    report["checked"].append({"bookingId": b["id"], "result": "hotel not found on Google Hotels"})
                    continue
            details = get({"engine": "google_hotels_property", "property_token": token, "free_cancellation": "true", **base_params(b)})
            report["searches"] += 1
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            hint = (" " + keys.missing("searchapi", "www.searchapi.io")) if e.code in (401, 403) else ""
            report["error"] = f"SearchApi returned HTTP {e.code}: {msg}{hint}"
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            report["error"] = f"Cannot reach www.searchapi.io ({e}). In a cloud session, allow it or add an API credential for it."
            break
        offer = best_free_cancel_offer(details)
        paid = float(b["price"]["amount"])
        if not offer:
            report["checked"].append({"bookingId": b["id"], "result": "no offer with free cancellation"})
            previous[b["id"]] = {**(previous.get(b["id"]) or {}), "bookingId": b["id"], "kind": "stay",
                                 "propertyToken": token, "checkedAt": now.isoformat(timespec="seconds"), "liveTotal": None}
            continue
        report["checked"].append({"bookingId": b["id"], "result": f"paid {paid:.0f}, now {offer['total']:.0f} with free cancellation ({offer['source']})"})
        previous[b["id"]] = {
            "bookingId": b["id"], "kind": "stay", "propertyToken": token,
            "paidTotal": round(paid, 2), "liveTotal": round(offer["total"], 2), "currency": b["price"].get("currency") or "EUR",
            "offerSource": offer["source"], "offerLink": offer["link"], "offerFreeCancelUntil": offer["freeCancelUntil"],
            "checkedAt": now.isoformat(timespec="seconds"), "source": "Google Hotels via SearchApi",
        }
    if len(due) > a.max_stays:
        report["skipped"] += [{"bookingId": b["id"], "reason": "over --max-stays"} for b in due[a.max_stays:]]

    stays = {b["id"] for b in check}
    results = [r for r in previous.values() if r.get("kind") != "stay" or r["bookingId"] in stays]
    Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
