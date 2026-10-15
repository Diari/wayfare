#!/usr/bin/env python3
"""Wayfare fare check (optional, experimental).

Looks for a lower fare on the SAME flight you already booked, using the
Duffel Flights API (https://duffel.com). It does not book or change
anything. You need your own Duffel access token in DUFFEL_ACCESS_TOKEN.

Limits you should know:
  * Duffel prices can differ from the airline's own website.
  * Only single-flight bookings are checked in v0.1 (no connections).
  * A test token (duffel_test_...) only returns Duffel's fake airline,
    so real flights never match in test mode.
  * Duffel may charge $0.005 per search above a 1500:1 search-to-booking
    ratio. If you never book through Duffel, every search counts. Keep
    --max-searches low.

Output: a JSON list that `wayfare.py build --fares` reads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.duffel.com/air/offer_requests?return_offers=true&supplier_timeout=20000"


def local_naive(iso: str) -> str:
    """'2026-11-12T12:10:00+00:00' -> '2026-11-12T12:10' (wall-clock time)."""
    return iso[:16]


def candidates(bookings: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """Return (to_check, skipped) single-flight bookings in the future with a price."""
    by_code: dict[str, list[dict]] = {}
    for b in bookings:
        if b.get("type") == "flight" and b.get("confirmation"):
            by_code.setdefault(b["confirmation"], []).append(b)
    check, skipped = [], []
    for b in bookings:
        if b.get("type") != "flight" or b.get("status") == "cancelled":
            continue
        try:
            dep = datetime.fromisoformat(b["depart"])
        except (KeyError, ValueError):
            continue
        if dep <= now:
            continue
        reason = None
        if not b.get("price") or not b["price"].get("amount"):
            reason = "no price paid found"
        elif len(by_code.get(b.get("confirmation"), [])) > 1:
            reason = "part of a connection or multi-flight booking (not supported in v0.1)"
        if reason:
            skipped.append({"bookingId": b["id"], "reason": reason})
        else:
            check.append(b)
    return check, skipped


def offer_request_body(b: dict) -> dict:
    cabin = (b.get("cabin") or "economy").lower().replace(" ", "_")
    if cabin not in {"economy", "premium_economy", "business", "first"}:
        cabin = "economy"
    n = int(b.get("travelers") or 1)
    return {"data": {
        "slices": [{"origin": b["from"], "destination": b["to"], "departure_date": b["depart"][:10]}],
        "passengers": [{"type": "adult"} for _ in range(n)],
        "cabin_class": cabin,
    }}


def best_matching_offer(b: dict, response: dict) -> dict | None:
    """Cheapest offer that is exactly the booked flight: one slice, one
    segment, same marketing carrier, flight number and local departure time."""
    best = None
    for o in (response.get("data") or {}).get("offers") or []:
        slices = o.get("slices") or []
        if len(slices) != 1 or len(slices[0].get("segments") or []) != 1:
            continue
        s = slices[0]["segments"][0]
        carrier = (s.get("marketing_carrier") or {}).get("iata_code")
        number = str(s.get("marketing_carrier_flight_number") or "").lstrip("0")
        if carrier != b.get("carrier") or number != str(b.get("flightNumber", "")).lstrip("0"):
            continue
        if (s.get("departing_at") or "")[:16] != local_naive(b["depart"]):
            continue
        amount = float(o["total_amount"])
        if best is None or amount < best["amount"]:
            best = {"amount": amount, "currency": o.get("total_currency"), "offerId": o.get("id")}
    return best


def post(body: dict, token: str, timeout: float = 40.0) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Duffel-Version": "v2",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bookings", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-searches", type=int, default=10)
    a = p.parse_args(argv)

    token = os.environ.get("DUFFEL_ACCESS_TOKEN", "").strip()
    data = json.loads(Path(a.bookings).read_text(encoding="utf-8"))
    bookings = data["bookings"] if isinstance(data, dict) else data
    now = datetime.now(timezone.utc)
    check, skipped = candidates(bookings, now)
    report = {"checked": [], "skipped": skipped, "searches": 0, "mode": None, "error": None}
    results: list[dict] = []

    if not token:
        report["error"] = "DUFFEL_ACCESS_TOKEN is not set. Fare checks are off."
    else:
        report["mode"] = "test" if token.startswith("duffel_test_") else "live"
        for b in check[: a.max_searches]:
            try:
                resp = post(offer_request_body(b), token)
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                report["error"] = f"Duffel returned HTTP {e.code}: {msg}"
                break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                report["error"] = (f"Cannot reach api.duffel.com ({e}). Cloud sessions often block outside APIs; "
                                   "run fare checks from Claude Code on your own computer.")
                break
            report["searches"] += 1
            match = best_matching_offer(b, resp)
            n = int(b.get("travelers") or 1)
            paid_pp = float(b["price"]["amount"]) / n
            if not match:
                report["checked"].append({"bookingId": b["id"], "result": "flight not found in offers"})
                continue
            if match["currency"] != b["price"]["currency"]:
                report["checked"].append({"bookingId": b["id"],
                                          "result": f"currency differs ({match['currency']} vs {b['price']['currency']}); not compared"})
                continue
            live_pp = match["amount"] / n
            report["checked"].append({"bookingId": b["id"], "result": f"paid {paid_pp:.2f}, now {live_pp:.2f} per traveller"})
            results.append({
                "bookingId": b["id"],
                "paidPerTraveler": round(paid_pp, 2),
                "livePerTraveler": round(live_pp, 2),
                "currency": match["currency"],
                "checkedAt": now.isoformat(timespec="seconds"),
                "source": "Duffel" + (" (test mode)" if report["mode"] == "test" else ""),
            })
        if len(check) > a.max_searches:
            report["skipped"] += [{"bookingId": b["id"], "reason": "over --max-searches"} for b in check[a.max_searches:]]

    Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
