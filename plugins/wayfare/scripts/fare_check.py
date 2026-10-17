#!/usr/bin/env python3
"""Wayfare fare check (optional).

Looks for a lower fare on the SAME flight you already booked. It does not
book or change anything. Two providers:

  searchapi (default)  Google Flights results through SearchApi
                       (https://www.searchapi.io).
  duffel               Duffel Flights API.
Keys: see keys.py.

Limits you should know:
  * The price is the public price for that flight and cabin today. Your fare
    rules decide whether you can get money back.
  * Only single-flight bookings are checked (no connections yet).
  * SearchApi gives 100 free searches, then about $4 per 1,000. Wayfare
    checks each flight at most every --every-days days (default 3).
  * Duffel may charge $0.005 per search when you search much more than you
    book through Duffel.

Output: a JSON list that `wayfare.py build --fares` reads.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path

import keys

API = "https://api.duffel.com/air/offer_requests?return_offers=true&supplier_timeout=20000"
SEARCHAPI = "https://www.searchapi.io/api/v1/search"
CABIN_SEARCHAPI = {"economy": "economy", "premium_economy": "premium_economy", "business": "business", "first": "first_class"}


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


def cabin_of(b: dict) -> str:
    c = (b.get("cabin") or "economy").lower().replace(" ", "_")
    return c if c in CABIN_SEARCHAPI else "economy"


def searchapi_params(b: dict) -> dict:
    return {"engine": "google_flights", "flight_type": "one_way", "departure_id": b["from"], "arrival_id": b["to"],
            "outbound_date": b["depart"][:10], "travel_class": CABIN_SEARCHAPI[cabin_of(b)],
            "adults": int(b.get("travelers") or 1), "currency": (b.get("price") or {}).get("currency") or "EUR",
            "hl": "en", "gl": "nl"}


def norm_flight(v: str) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum()).lstrip("0")


def hhmm(v: str) -> str:
    v = str(v or "").strip()
    return v[-5:] if len(v) >= 5 and v[-3] == ":" else v


def searchapi_match(b: dict, resp: dict) -> dict | None:
    """Cheapest one-segment result with the same flight number and departure time.
    SearchApi (like Google Flights) gives the total price for all adults."""
    want = norm_flight(f"{b.get('carrier', '')}{b.get('flightNumber', '')}")
    dep_time = b["depart"][11:16]
    best = None
    for group in ("best_flights", "other_flights", "flights"):
        for o in resp.get(group) or []:
            segs = o.get("flights") or []
            if len(segs) != 1 or o.get("price") in (None, ""):
                continue
            s = segs[0]
            if norm_flight(s.get("flight_number")) != want:
                continue
            if hhmm((s.get("departure_airport") or {}).get("time")) != dep_time:
                continue
            amount = float(o["price"])
            if best is None or amount < best["amount"]:
                best = {"amount": amount, "currency": searchapi_params(b)["currency"]}
    return best


def searchapi_get(params: dict, timeout: float = 60.0) -> dict:
    headers = {"Accept": "application/json"}
    key = keys.get("searchapi")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = SEARCHAPI + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(body: dict, token: str, timeout: float = 40.0) -> dict:
    headers = {"Duffel-Version": "v2", "Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def recently_checked(previous: dict[str, dict], booking_id: str, now: datetime, every_days: float) -> bool:
    r = previous.get(booking_id)
    if not r:
        return False
    try:
        return now - datetime.fromisoformat(r["checkedAt"].replace("Z", "+00:00")) < timedelta(days=every_days)
    except (KeyError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bookings", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--provider", choices=["searchapi", "duffel"], default="searchapi")
    p.add_argument("--previous", help="earlier fare results (kept; flights checked recently are skipped)")
    p.add_argument("--every-days", type=float, default=3)
    p.add_argument("--max-searches", type=int, default=6)
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
    due = []
    for b in check:
        if recently_checked(previous, b["id"], now, a.every_days):
            skipped.append({"bookingId": b["id"], "reason": f"checked in the last {a.every_days:g} days"})
        else:
            due.append(b)
    report = {"provider": a.provider, "checked": [], "skipped": skipped, "searches": 0, "mode": None, "error": None}

    token = keys.get("duffel")
    if a.provider == "duffel":
        report["mode"] = "test" if token.startswith("duffel_test_") else ("live" if token else "key from " + keys.WHERE)
    else:
        report["mode"] = "key from " + keys.WHERE

    for b in due[: a.max_searches]:
        try:
            if a.provider == "duffel":
                match = best_matching_offer(b, post(offer_request_body(b), token))
            else:
                match = searchapi_match(b, searchapi_get(searchapi_params(b)))
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            hint = ""
            if e.code in (401, 403):
                hint = " " + (keys.missing("searchapi", "www.searchapi.io") if a.provider == "searchapi"
                              else keys.missing("duffel", "api.duffel.com"))
            report["error"] = f"{a.provider} returned HTTP {e.code}: {msg}{hint}"
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            host = "www.searchapi.io" if a.provider == "searchapi" else "api.duffel.com"
            report["error"] = f"Cannot reach {host} ({e}). In a cloud session, allow {host} or add an API credential for it."
            break
        report["searches"] += 1
        n = int(b.get("travelers") or 1)
        paid_pp = float(b["price"]["amount"]) / n
        if not match:
            report["checked"].append({"bookingId": b["id"], "result": "flight not found in results"})
            continue
        if match["currency"] != b["price"]["currency"]:
            report["checked"].append({"bookingId": b["id"],
                                      "result": f"currency differs ({match['currency']} vs {b['price']['currency']}); not compared"})
            continue
        live_pp = match["amount"] / n
        report["checked"].append({"bookingId": b["id"], "result": f"paid {paid_pp:.2f}, now {live_pp:.2f} per traveller"})
        previous[b["id"]] = {
            "bookingId": b["id"], "paidPerTraveler": round(paid_pp, 2), "livePerTraveler": round(live_pp, 2),
            "currency": match["currency"], "checkedAt": now.isoformat(timespec="seconds"),
            "source": "Google Flights via SearchApi" if a.provider == "searchapi" else
                      "Duffel" + (" (test mode)" if report["mode"] == "test" else ""),
        }
    if len(due) > a.max_searches:
        report["skipped"] += [{"bookingId": b["id"], "reason": "over --max-searches"} for b in due[a.max_searches:]]

    future = {b["id"] for b in bookings if b.get("type") == "flight" and b.get("status") != "cancelled"
              and datetime.fromisoformat(b["depart"]) > now}
    # Keep stay records from stay_check.py as they are; they share this file.
    results = [r for r in previous.values() if r.get("kind") == "stay" or r["bookingId"] in future]
    Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
