#!/usr/bin/env python3
"""Wayfare planner: trips you have NOT booked yet ("plans").

A plan holds what you want: where and why, dates, who travels, flight times
and stay wishes. The planner searches Google Flights and Google Hotels
(through SearchApi), keeps a price history, and raises an alert when a price
drops. It never books or pays: you book yourself, then the plan becomes a
normal trip when the booking emails arrive.

Commands
  validate   Check plans.json.
  search     Search prices for due plans and update the price state
             (needs SearchApi; see keys.py and dashboard-io.md J).
  reconcile  Mark plan parts as booked when matching bookings exist.
  build      Write the plan page batches and Home's index/plans.
  link       Print search links for one plan (no network).

Cost: about 3-4 SearchApi searches per plan per check (one per flight leg
and airport pair, one for stays, one per preferred stay). Plans more than
60 days away are checked every 3 days, closer plans every day.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import keys
import wayfare as W

SEARCHAPI = "https://www.searchapi.io/api/v1/search"
GEO = "https://geocoding-api.open-meteo.com/v1/search"
CABINS = {"economy": "economy", "premium_economy": "premium_economy", "business": "business", "first": "first_class"}
STATUSES = {"watching", "paused", "booked", "ended"}
HISTORY_MAX = 90
TOP_FLIGHTS = 5
TOP_STAYS = 6
DEFAULT_ALERTS = {"minDropAmount": 20, "minDropPercent": 5}
HHMM = re.compile(r"^\d{2}:\d{2}$")
IATA = re.compile(r"^[A-Z]{3}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")


# ----------------------------------------------------------------- model

def validate_plan(p: Any, i: int) -> list[str]:
    where = f"plans[{i}] ({p.get('id', '?') if isinstance(p, dict) else '?'})"
    if not isinstance(p, dict):
        return [f"plans[{i}]: must be an object"]
    errs: list[str] = []
    if not SLUG.match(str(p.get("id", ""))):
        errs.append(f"{where}: id must be lowercase letters, digits and '-' (e.g. teulada-2027-06)")
    if not p.get("title"):
        errs.append(f"{where}: missing title")
    if p.get("status", "watching") not in STATUSES:
        errs.append(f"{where}: status must be one of {sorted(STATUSES)}")
    t = p.get("travellers") or {}
    if not isinstance(t.get("adults"), int) or not 1 <= t["adults"] <= 9:
        errs.append(f"{where}: travellers.adults must be 1-9")
    ages = t.get("childrenAges", [])
    if not isinstance(ages, list) or not all(isinstance(a, int) and 0 <= a <= 17 for a in ages):
        errs.append(f"{where}: travellers.childrenAges must be a list of ages 0-17")
    fl = p.get("flights")
    if fl is not None:
        for leg in ("out", "back"):
            L = fl.get(leg)
            if L is None:
                continue
            for k in ("from", "to"):
                if not L.get(k) or not all(IATA.match(x) for x in L[k]):
                    errs.append(f"{where}: flights.{leg}.{k} must be a list of IATA airport codes")
            try:
                date.fromisoformat(L.get("date", ""))
            except ValueError:
                errs.append(f"{where}: flights.{leg}.date must be YYYY-MM-DD")
            for k in ("departAfter", "departBefore", "arriveAfter", "arriveBefore"):
                if L.get(k) is not None and not HHMM.match(str(L[k])):
                    errs.append(f"{where}: flights.{leg}.{k} must be HH:MM")
        if fl.get("cabin", "economy") not in CABINS:
            errs.append(f"{where}: flights.cabin must be one of {sorted(CABINS)}")
        if fl.get("maxStops") is not None and fl["maxStops"] not in (0, 1, 2):
            errs.append(f"{where}: flights.maxStops must be 0, 1, 2 or null")
        out, back = fl.get("out"), fl.get("back")
        if out and back and back.get("date", "") < out.get("date", ""):
            errs.append(f"{where}: flights.back.date is before flights.out.date")
    st = p.get("stay")
    if st is not None:
        try:
            ci, co = date.fromisoformat(st.get("checkIn", "")), date.fromisoformat(st.get("checkOut", ""))
            if co <= ci:
                errs.append(f"{where}: stay.checkOut must be after stay.checkIn")
        except ValueError:
            errs.append(f"{where}: stay.checkIn/checkOut must be YYYY-MM-DD")
        if not (st.get("near") or st.get("city")):
            errs.append(f"{where}: stay needs 'near' or 'city'")
        if st.get("minStars") is not None and st["minStars"] not in (2, 3, 4, 5):
            errs.append(f"{where}: stay.minStars must be 2-5")
    if not p.get("flights") and not p.get("stay"):
        errs.append(f"{where}: a plan needs flights, a stay, or both")
    return errs


def validate(plans: Any) -> list[str]:
    if not isinstance(plans, list):
        return ["plans must be a JSON array"]
    errs, seen = [], set()
    for i, p in enumerate(plans):
        errs += validate_plan(p, i)
        if isinstance(p, dict):
            if p.get("id") in seen:
                errs.append(f"plans[{i}]: duplicate id {p.get('id')}")
            seen.add(p.get("id"))
    return errs


def plan_start(p: dict) -> str:
    ds = [L["date"] for L in (p.get("flights") or {}).values() if isinstance(L, dict) and L.get("date")]
    if p.get("stay"):
        ds.append(p["stay"]["checkIn"])
    return min(ds) if ds else "9999-12-31"


def plan_end(p: dict) -> str:
    ds = [L["date"] for L in (p.get("flights") or {}).values() if isinstance(L, dict) and L.get("date")]
    if p.get("stay"):
        ds.append(p["stay"]["checkOut"])
    return max(ds) if ds else "0000-01-01"


def pax(p: dict) -> dict:
    """Flight passengers: under 2 on lap, 2-11 children, 12+ adults (airline rules)."""
    t = p["travellers"]
    ages = t.get("childrenAges", [])
    return {"adults": t["adults"] + sum(1 for a in ages if a >= 12),
            "children": sum(1 for a in ages if 2 <= a <= 11),
            "infants_on_lap": sum(1 for a in ages if a < 2)}


def travellers_label(p: dict) -> str:
    t = p["travellers"]
    a = f"{t['adults']} adult{'s' if t['adults'] != 1 else ''}"
    ages = t.get("childrenAges", [])
    if not ages:
        return a
    return f"{a}, {len(ages)} child{'ren' if len(ages) != 1 else ''} ({', '.join(str(x) for x in ages)})"


def booked(p: dict, part: str) -> bool:
    return bool((p.get("booked") or {}).get(part))


# ----------------------------------------------------------------- SearchApi

def searchapi_get(params: dict, timeout: float = 60.0) -> dict:
    headers = {"Accept": "application/json"}
    key = keys.get("searchapi")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    url = SEARCHAPI + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode())


def flight_params(p: dict, leg: str, frm: str, to: str) -> dict:
    fl, L = p["flights"], p["flights"][leg]
    q = {"engine": "google_flights", "flight_type": "one_way", "departure_id": frm, "arrival_id": to,
         "outbound_date": L["date"], "travel_class": CABINS[fl.get("cabin", "economy")],
         "currency": p.get("currency", "EUR"), "hl": "en", "gl": p.get("gl", "nl")}
    for k, v in pax(p).items():
        if v:
            q[k] = v
    return q


def stay_params(p: dict) -> dict:
    st = p["stay"]
    stars = st.get("minStars")
    q = {"engine": "google_hotels", "q": stay_query(p), "check_in_date": st["checkIn"], "check_out_date": st["checkOut"],
         "adults": p["travellers"]["adults"], "currency": p.get("currency", "EUR"), "hl": "en", "gl": p.get("gl", "nl")}
    ages = p["travellers"].get("childrenAges", [])
    if ages:
        q["children_ages"] = ",".join(str(a) for a in ages)
    if stars:
        q["hotel_class"] = ",".join(str(s) for s in range(stars, 6))
    if st.get("freeCancellation"):
        q["free_cancellation"] = "true"
    return q


def stay_query(p: dict) -> str:
    st = p["stay"]
    kind = {"apartment": "apartments", "villa": "villas"}.get(st.get("kind", "hotel"), "hotels")
    place = st.get("near") or st.get("city")
    return f"{kind} near {place}"


def hhmm(v: Any) -> str:
    v = str(v or "").strip()
    return v[-5:] if len(v) >= 5 and v[-3] == ":" else v


def seg_date(a: dict) -> str:
    d = str(a.get("date") or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", d):
        return d[:10]
    t = str(a.get("time") or "")
    return t[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", t) else ""


def parse_flights(resp: dict, frm: str, to: str, leg_date: str) -> list[dict]:
    out = []
    for group in ("best_flights", "other_flights", "flights"):
        for o in resp.get(group) or []:
            segs = o.get("flights") or []
            price = o.get("price")
            if not segs or price in (None, "") or not isinstance(price, (int, float, str)):
                continue
            try:
                amount = float(str(price).replace(",", "").lstrip("€$£ "))
            except ValueError:
                continue
            d0, a1 = segs[0].get("departure_airport") or {}, segs[-1].get("arrival_airport") or {}
            arr_date = seg_date(a1) or leg_date
            out.append({
                "from": d0.get("id") or frm, "to": a1.get("id") or to,
                "dep": hhmm(d0.get("time")), "arr": hhmm(a1.get("time")),
                "arrNextDay": arr_date > leg_date,
                "stops": len(segs) - 1,
                "airlines": sorted({s.get("airline") for s in segs if s.get("airline")}),
                "flights": [str(s.get("flight_number") or "").replace(" ", "") for s in segs],
                "via": [ (s.get("arrival_airport") or {}).get("id") for s in segs[:-1]],
                "minutes": o.get("total_duration"),
                "price": round(amount, 2),
                "googleBest": group == "best_flights",
            })
    return out


def flight_ok(o: dict, L: dict, max_stops: int | None) -> tuple[bool, str]:
    if max_stops is not None and o["stops"] > max_stops:
        return False, "stops"
    if not HHMM.match(o["dep"]) or not HHMM.match(o["arr"]):
        return False, "time"
    if L.get("departAfter") and o["dep"] < L["departAfter"]:
        return False, "early"
    if L.get("departBefore") and o["dep"] > L["departBefore"]:
        return False, "late"
    if L.get("arriveAfter") and not o["arrNextDay"] and o["arr"] < L["arriveAfter"]:
        return False, "early"
    if L.get("arriveBefore") and (o["arrNextDay"] or o["arr"] > L["arriveBefore"]):
        return False, "late"
    if L.get("airlines") and not set(L["airlines"]) & set(o["airlines"]):
        return False, "airline"
    return True, ""


def rank_flights(opts: list[dict], L: dict, max_stops: int | None) -> tuple[list[dict], dict]:
    seen, keep, why = set(), [], {}
    for o in sorted(opts, key=lambda x: (x["price"], x.get("minutes") or 9999)):
        key = (tuple(o["flights"]), o["dep"])
        if key in seen:
            continue
        seen.add(key)
        ok, reason = flight_ok(o, L, max_stops)
        if ok:
            keep.append(o)
        else:
            why[reason] = why.get(reason, 0) + 1
    return keep[:TOP_FLIGHTS], {"found": len(seen), "matching": len(keep), "excluded": why}


def num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("extracted_lowest", "extracted_price", "extracted_before_taxes_fees"):
            if isinstance(v.get(k), (int, float)):
                return float(v[k])
    if isinstance(v, str):
        m = re.search(r"[\d.,]+", v)
        if m:
            try:
                return float(m.group(0).replace(",", ""))
            except ValueError:
                return None
    return None


def stars_of(h: dict) -> int | None:
    for k in ("extracted_hotel_class", "hotel_class", "class"):
        v = h.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            m = re.search(r"([1-5])", v)
            if m:
                return int(m.group(1))
    return None


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)), 1)


def parse_stays(resp: dict, nights: int, near: tuple[float, float] | None) -> list[dict]:
    out = []
    for h in resp.get("properties") or []:
        name = h.get("name")
        total = num(h.get("total_price")) or num(h.get("total_rate"))
        per = num(h.get("price_per_night")) or num(h.get("rate_per_night"))
        if total is None and per is not None:
            total = per * nights
        if not name or total is None or total <= 0:
            continue
        gps = h.get("gps_coordinates") or {}
        where = (gps.get("latitude"), gps.get("longitude"))
        link = h.get("link")
        out.append({
            "name": str(name)[:120], "token": h.get("property_token"),
            "stars": stars_of(h), "rating": h.get("rating") or h.get("overall_rating"),
            "reviews": h.get("reviews"), "type": h.get("type"),
            "total": round(total, 2), "perNight": round(per if per is not None else total / max(nights, 1), 2),
            "km": km(near, where) if near and all(isinstance(x, (int, float)) for x in where) else None,
            "freeCancel": bool(h.get("free_cancellation") or h.get("has_free_cancellation")
                               or "free cancellation" in json.dumps(h.get("deal") or h.get("deal_description") or "").lower()),
            "link": link if isinstance(link, str) and link.startswith("https://") else None,
        })
    return out


def same_hotel(a: str, b: str) -> bool:
    stop = {"hotel", "the", "resort", "and", "spa", "apartments", "apartamentos", "&", "-"}
    wa = {w for w in re.findall(r"[a-z0-9]+", a.lower()) if w not in stop}
    wb = {w for w in re.findall(r"[a-z0-9]+", b.lower()) if w not in stop}
    return bool(wa) and bool(wb) and (wa <= wb or wb <= wa or len(wa & wb) >= 2)


def rank_stays(opts: list[dict], st: dict) -> tuple[list[dict], dict]:
    minst, maxkm, minrating = st.get("minStars"), st.get("maxDistanceKm"), st.get("minRating")
    prefs = st.get("preferred") or []
    seen, keep, why = set(), [], {}
    for o in sorted(opts, key=lambda x: x["total"]):
        k = o["name"].lower()
        if k in seen:
            continue
        seen.add(k)
        o["preferred"] = any(same_hotel(o["name"], p) for p in prefs)
        reason = None
        if not o["preferred"]:
            if minst and (o["stars"] is None or o["stars"] < minst):
                reason = "stars"
            elif maxkm and o["km"] is not None and o["km"] > maxkm:
                reason = "distance"
            elif minrating and isinstance(o["rating"], (int, float)) and o["rating"] < minrating:
                reason = "rating"
        if reason:
            why[reason] = why.get(reason, 0) + 1
        else:
            keep.append(o)
    pref = [o for o in keep if o["preferred"]]
    rest = [o for o in keep if not o["preferred"]][:TOP_STAYS]
    return pref + rest, {"found": len(seen), "matching": len(keep), "excluded": why}


def geocode(place: str) -> tuple[float, float] | None:
    url = GEO + "?" + urllib.parse.urlencode({"name": place, "count": 1, "language": "en", "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "wayfare-plugin"}), timeout=20) as r:
        hits = json.loads(r.read().decode()).get("results") or []
    return (hits[0]["latitude"], hits[0]["longitude"]) if hits else None


# ----------------------------------------------------------------- price state

def due(p: dict, prev: dict | None, now: datetime, every_hours: float | None) -> bool:
    if p.get("status", "watching") != "watching" or plan_end(p) < now.date().isoformat():
        return False
    if not prev or not prev.get("checkedAt"):
        return True
    if every_hours is None:
        days_away = (date.fromisoformat(plan_start(p)) - now.date()).days
        every_hours = 72 if days_away > 60 else 20
    last = datetime.fromisoformat(prev["checkedAt"])
    return now - last >= timedelta(hours=every_hours)


def push_history(hist: list, at: str, value: float | None) -> list:
    if value is None:
        return hist
    day = at[:10]
    hist = [h for h in hist if h[0] != day] + [[day, value]]
    return hist[-HISTORY_MAX:]


def lowest(hist: list) -> float | None:
    return min((h[1] for h in hist), default=None)


def search_plan(p: dict, prev: dict | None, now: datetime, fetch=searchapi_get, near_lookup=geocode) -> tuple[dict, int]:
    """Search one plan. Returns (record, searches used). Raises on network errors."""
    at = now.isoformat(timespec="seconds")
    rec: dict[str, Any] = {"planId": p["id"], "checkedAt": at, "currency": p.get("currency", "EUR"),
                           "legs": {}, "stay": None, "history": dict((prev or {}).get("history") or {})}
    used = 0
    fl = p.get("flights") or {}
    for leg in ("out", "back"):
        L = fl.get(leg)
        if not L or booked(p, leg):
            continue
        opts = []
        for frm in L["from"][:2]:
            for to in L["to"][:2]:
                opts += parse_flights(fetch(flight_params(p, leg, frm, to)), frm, to, L["date"])
                used += 1
        top, stats = rank_flights(opts, L, fl.get("maxStops"))
        cheapest = top[0]["price"] if top else None
        rec["legs"][leg] = {"options": top, "stats": stats, "cheapest": cheapest}
        rec["history"][leg] = push_history(list(rec["history"].get(leg) or []), at, cheapest)
    st = p.get("stay")
    if st and not booked(p, "stay"):
        near = None
        if isinstance(st.get("nearLat"), (int, float)) and isinstance(st.get("nearLon"), (int, float)):
            near = (st["nearLat"], st["nearLon"])
        elif st.get("maxDistanceKm"):
            try:
                near = near_lookup(st.get("near") or st.get("city")) or (near_lookup(st["city"]) if st.get("city") else None)
            except (urllib.error.URLError, OSError, ValueError):
                near = None
        nights = (date.fromisoformat(st["checkOut"]) - date.fromisoformat(st["checkIn"])).days
        # Google Hotels can answer nothing when the stars and free-cancellation
        # filters are combined (seen live, October 2026). Then search again with
        # fewer filters; the stars are also checked here, on each result.
        relaxed: list[str] = []
        q = stay_params(p)
        opts = parse_stays(fetch(q), nights, near)
        used += 1
        for drop_key, label in (("free_cancellation", "free cancellation"), ("hotel_class", "stars")):
            if opts or drop_key not in q:
                continue
            q = {k: v for k, v in q.items() if k != drop_key}
            relaxed.append(label)
            opts = parse_stays(fetch(q), nights, near)
            used += 1
        for pref in (st.get("preferred") or [])[:2]:
            if not any(same_hotel(o["name"], pref) for o in opts):
                q = dict(stay_params(p), q=pref)
                q.pop("hotel_class", None)
                opts += [o for o in parse_stays(fetch(q), nights, near) if same_hotel(o["name"], pref)][:1]
                used += 1
        top, stats = rank_stays(opts, st)
        cheapest = min((o["total"] for o in top), default=None)
        stats["relaxed"] = relaxed
        rec["stay"] = {"options": top, "stats": stats, "cheapest": cheapest, "nights": nights,
                       "nearFound": near is not None}
        rec["history"]["stay"] = push_history(list(rec["history"].get("stay") or []), at, cheapest)
        for o in top:
            if o["preferred"]:
                k = "pref:" + o["name"].lower()[:60]
                rec["history"][k] = push_history(list(rec["history"].get(k) or []), at, o["total"])
    parts = [rec["legs"].get("out", {}).get("cheapest"), rec["legs"].get("back", {}).get("cheapest"),
             (rec["stay"] or {}).get("cheapest")]
    wanted = [x for x, part in zip(parts, ("out", "back", "stay"))
              if (part == "stay" and st and not booked(p, "stay")) or (part != "stay" and fl.get(part) and not booked(p, part))]
    rec["total"] = round(sum(wanted), 2) if wanted and all(x is not None for x in wanted) else None
    rec["history"]["total"] = push_history(list(rec["history"].get("total") or []), at, rec["total"])
    return rec, used


# ----------------------------------------------------------------- alerts

def drop_enough(new: float, old: float, rules: dict) -> bool:
    d = old - new
    return d >= rules["minDropAmount"] and d >= old * rules["minDropPercent"] / 100


def plan_alerts(p: dict, rec: dict | None) -> list[dict]:
    """Alerts for the plan page. A drop alert compares this check's cheapest
    price with the last price on an earlier day (from the price history),
    and says how it compares with the lowest price seen before."""
    if not rec:
        return []
    rules = dict(DEFAULT_ALERTS, **(p.get("alerts") or {}))
    cur = rec.get("currency", "EUR")
    out: list[dict] = []
    fl = p.get("flights") or {}

    def earlier(series: str) -> list:
        h = (rec.get("history") or {}).get(series) or []
        return [x for x in h if x[0] < rec["checkedAt"][:10]]

    def prev_val(series: str) -> float | None:
        h = earlier(series)
        return h[-1][1] if h else None

    def low_before(series: str) -> float | None:
        return lowest(earlier(series))

    def drop(series: str, new: float | None, kind: str, title: str, what: str, link: str | None) -> None:
        old = prev_val(series)
        if new is None or old is None or not drop_enough(new, old, rules):
            return
        low = low_before(series)
        best = " That is the lowest price Wayfare has seen." if low is None or new < low else \
            f" The lowest seen was {cur} {low:.0f}."
        out.append({"level": "info", "kind": kind, "id": f"{kind}-{series}"[:60], "title": title,
                    "detail": f"{what} now {cur} {new:.0f}, was {cur} {old:.0f} at the last check.{best} "
                              "Prices change often. Book on the airline or hotel site if it suits you.",
                    "link": link})

    labels = {"out": "Outbound flight", "back": "Return flight"}
    for leg, L in fl.items():
        if leg not in labels or not L or booked(p, leg):
            continue
        r = (rec.get("legs") or {}).get(leg)
        if r is None:
            continue
        route = f"{'/'.join(L['from'])} → {'/'.join(L['to'])}"
        when = W.day_label(date.fromisoformat(L["date"]))
        if not r["options"]:
            ex = r["stats"]["excluded"]
            note = " ".join(f"{n} {k}" for k, n in ex.items())
            out.append({"level": "medium", "kind": "plan_no_flights", "id": f"plan_no_flights-{leg}",
                        "title": f"No {labels[leg].lower()} matches your times",
                        "detail": f"{route} on {when}: {r['stats']['found']} flights found, none inside your wishes"
                                  f"{' (' + note + ')' if note else ''}. Widen the time window or allow a stop.",
                        "link": google_flights_url(p, leg)})
            continue
        drop(leg, r["cheapest"], "plan_flight_drop", f"{labels[leg]} is cheaper",
             f"{route} on {when} (total for {travellers_label(p)}):", google_flights_url(p, leg))
    st = p.get("stay")
    s = rec.get("stay")
    if st and s and not booked(p, "stay"):
        if not s["options"]:
            out.append({"level": "medium", "kind": "plan_no_stays", "id": "plan_no_stays",
                        "title": "No stay matches your wishes",
                        "detail": f"{s['stats']['found']} places found near {st.get('near') or st.get('city')}, none with "
                                  "your stars, distance and rating. Lower the stars or widen the distance.",
                        "link": booking_url(p)})
        else:
            cheapest_is_pref = any(o["preferred"] and o["total"] == s["cheapest"] for o in s["options"])
            if not cheapest_is_pref:
                drop("stay", s["cheapest"], "plan_stay_drop", "A stay is cheaper",
                     f"The cheapest matching stay for {s['nights']} nights:", booking_url(p))
            for o in s["options"]:
                if o["preferred"]:
                    k = "pref:" + o["name"].lower()[:60]
                    drop(k, o["total"], "plan_pref_drop", f"{o['name']} is cheaper", f"{o['name']} for {s['nights']} nights:",
                         o.get("link") or booking_url(p))
    return out


# ----------------------------------------------------------------- links

def google_flights_url(p: dict, leg: str) -> str:
    L = p["flights"][leg]
    x = pax(p)
    who = f"{x['adults']} adults" + (f" {x['children']} children" if x["children"] else "") + \
          (f" {x['infants_on_lap']} infants on lap" if x["infants_on_lap"] else "")
    q = f"Flights from {L['from'][0]} to {L['to'][0]} on {L['date']} one way {who}"
    return "https://www.google.com/travel/flights?" + urllib.parse.urlencode({"q": q, "curr": p.get("currency", "EUR")})


def booking_url(p: dict) -> str:
    st = p["stay"]
    ages = p["travellers"].get("childrenAges", [])
    q: list[tuple[str, Any]] = [("ss", st.get("near") or st.get("city")), ("checkin", st["checkIn"]),
                                ("checkout", st["checkOut"]), ("group_adults", p["travellers"]["adults"]),
                                ("group_children", len(ages)), ("no_rooms", st.get("rooms", 1))]
    q += [("age", a) for a in ages]
    if st.get("minStars"):
        q.append(("nflt", ";".join(f"class={s}" for s in range(st["minStars"], 6))))
    return "https://www.booking.com/searchresults.html?" + urllib.parse.urlencode(q)


def google_hotels_url(p: dict) -> str:
    st = p["stay"]
    return "https://www.google.com/travel/search?" + urllib.parse.urlencode(
        {"q": f"{stay_query(p)} {st['checkIn']} to {st['checkOut']}"})


# ----------------------------------------------------------------- reconcile

def reconcile(plans: list[dict], bookings: list[dict]) -> list[str]:
    """Mark plan parts as booked when a real booking matches. Returns notes."""
    notes = []
    live = [b for b in bookings if b.get("status") != "cancelled"]
    for p in plans:
        if p.get("status") in ("ended",):
            continue
        bk = dict(p.get("booked") or {})
        for leg, L in (p.get("flights") or {}).items():
            if not isinstance(L, dict) or bk.get(leg):
                continue
            for b in live:
                if b.get("type") == "flight" and b.get("depart", "")[:10] == L["date"] \
                        and b.get("from") in L["from"] and b.get("to") in L["to"]:
                    bk[leg] = b["id"]; notes.append(f"{p['id']}: {leg} flight booked ({b['id']})"); break
        st = p.get("stay")
        if st and not bk.get("stay"):
            for b in live:
                if b.get("type") == "hotel" and b.get("checkIn") == st["checkIn"]:
                    bk["stay"] = b["id"]; notes.append(f"{p['id']}: stay booked ({b['id']})"); break
        if bk != (p.get("booked") or {}):
            p["booked"] = bk
            parts = [k for k in ("out", "back") if (p.get("flights") or {}).get(k)] + (["stay"] if st else [])
            if parts and all(bk.get(k) for k in parts):
                p["status"] = "booked"
    return notes


# ----------------------------------------------------------------- page data

def leg_view(p: dict, leg: str, rec: dict | None) -> dict | None:
    L = (p.get("flights") or {}).get(leg)
    if not L:
        return None
    wish = []
    if L.get("departAfter") or L.get("departBefore"):
        wish.append(f"leave {L.get('departAfter', '00:00')}–{L.get('departBefore', '23:59')}")
    if L.get("arriveAfter") or L.get("arriveBefore"):
        wish.append(f"arrive {('after ' + L['arriveAfter']) if L.get('arriveAfter') else ''}"
                    f"{' and ' if L.get('arriveAfter') and L.get('arriveBefore') else ''}"
                    f"{('by ' + L['arriveBefore']) if L.get('arriveBefore') else ''}")
    ms = (p.get("flights") or {}).get("maxStops")
    if ms is not None:
        wish.append("direct only" if ms == 0 else f"at most {ms} stop{'s' if ms > 1 else ''}")
    r = (rec or {}).get("legs", {}).get(leg)
    hist = ((rec or {}).get("history") or {}).get(leg) or []
    return {"key": leg, "title": "Outbound" if leg == "out" else "Return",
            "label": f"{W.day_label(date.fromisoformat(L['date']))} · {'/'.join(L['from'])} → {'/'.join(L['to'])}",
            "wishes": wish, "booked": booked(p, leg),
            "options": (r or {}).get("options", []), "stats": (r or {}).get("stats"),
            "cheapest": (r or {}).get("cheapest"), "lowest": lowest(hist), "history": hist[-30:],
            "link": google_flights_url(p, leg)}


def stay_view(p: dict, rec: dict | None) -> dict | None:
    st = p.get("stay")
    if not st:
        return None
    ci, co = date.fromisoformat(st["checkIn"]), date.fromisoformat(st["checkOut"])
    wish = []
    if st.get("minStars"):
        wish.append(f"{st['minStars']}+ stars")
    if st.get("maxDistanceKm"):
        wish.append(f"within {st['maxDistanceKm']} km")
    if st.get("freeCancellation"):
        wish.append("free cancellation")
    s0 = (rec or {}).get("stay") or {}
    if "free cancellation" in ((s0.get("stats") or {}).get("relaxed") or []):
        wish.append("free cancellation: check each place (the search filter found nothing)")
    if st.get("rooms", 1) > 1:
        wish.append(f"{st['rooms']} rooms")
    if st.get("notes"):
        wish.append(str(st["notes"])[:80])
    s = (rec or {}).get("stay")
    hist = ((rec or {}).get("history") or {}).get("stay") or []
    return {"label": f"{W.range_label(ci, co)} · near {st.get('near') or st.get('city')}",
            "nights": (co - ci).days, "wishes": wish, "booked": booked(p, "stay"),
            "preferred": st.get("preferred") or [],
            "options": (s or {}).get("options", []), "stats": (s or {}).get("stats"),
            "cheapest": (s or {}).get("cheapest"), "lowest": lowest(hist), "history": hist[-30:],
            "links": {"booking": booking_url(p), "google": google_hotels_url(p)}}


def plan_page(p: dict, rec: dict | None, now: datetime) -> dict:
    s, e = date.fromisoformat(plan_start(p)), date.fromisoformat(plan_end(p))
    hist = ((rec or {}).get("history") or {}).get("total") or []
    status = p.get("status", "watching")
    if status == "watching" and e < now.date():
        status = "ended"
    return {
        "id": p["id"], "title": p["title"], "purpose": p.get("purpose"), "status": status,
        "dates": W.range_label(s, e), "startDate": s.isoformat(), "endDate": e.isoformat(),
        "destination": p.get("destination") or {}, "travellers": travellers_label(p),
        "cabin": (p.get("flights") or {}).get("cabin", "economy"), "currency": p.get("currency", "EUR"),
        "legs": [v for v in (leg_view(p, "out", rec), leg_view(p, "back", rec)) if v],
        "stay": stay_view(p, rec),
        "total": (rec or {}).get("total"), "totalLowest": lowest(hist), "totalHistory": hist[-30:],
        "alerts": plan_alerts(p, rec),
        "notes": p.get("notes") or [],
        "checkedAt": (rec or {}).get("checkedAt"),
        "error": (rec or {}).get("lastError") if (rec or {}).get("lastErrorAt", "") > ((rec or {}).get("checkedAt") or "") else None,
        "errorAt": (rec or {}).get("lastErrorAt"),
        "updatedAt": now.isoformat(timespec="seconds"), "engineVersion": W.ENGINE_VERSION,
    }


def index_entry(page: dict, url: str | None) -> dict:
    return {"id": page["id"], "title": page["title"], "dates": page["dates"], "startDate": page["startDate"],
            "status": page["status"], "url": url, "currency": page["currency"], "total": page["total"],
            "totalLowest": page["totalLowest"], "checkedAt": page["checkedAt"],
            "alerts": len(page["alerts"]), "travellers": page["travellers"],
            "trend": [h[1] for h in page["totalHistory"][-14:]]}


PLAN_CAPABILITIES = {
    "db": {"rules": [
        {"path": "", "read": "view", "write": "owner"},
        {"path": "private", "read": "owner", "write": "owner"},
        {"path": "requests", "read": "owner", "write": "owner"},
    ]},
    "user": {},
    "mcp": {"servers": [{"server": "Claude Code Remote", "tools": ["fire_trigger"]}]},
}


# ----------------------------------------------------------------- CLI

def load(path: str | None, default: Any) -> Any:
    if not path or not Path(path).exists() or not Path(path).read_text().strip():
        return default
    return W.unwrap(json.loads(Path(path).read_text(encoding="utf-8")))


def load_plans(path: str) -> list[dict]:
    d = load(path, [])
    return d.get("plans", []) if isinstance(d, dict) else d


def load_prices(path: str | None) -> dict:
    d = load(path, {})
    return d.get("results", d) if isinstance(d, dict) else {}


def cmd_validate(a) -> int:
    errs = validate(load_plans(a.plans))
    print("\n".join(errs) if errs else "plans: OK")
    return 1 if errs else 0


def fixture_fetch(folder: str):
    """Tests: answer from JSON files named after the request."""
    def f(params: dict) -> dict:
        if params["engine"] == "google_flights":
            name = f"flights_{params['departure_id']}_{params['arrival_id']}_{params['outbound_date']}.json"
        else:
            name = "hotels_" + re.sub(r"[^a-z0-9]+", "-", params["q"].lower()).strip("-") + ".json"
        path = Path(folder) / name
        return json.loads(path.read_text()) if path.exists() else {}
    return f


def cmd_search(a) -> int:
    plans = load_plans(a.plans)
    errs = validate(plans)
    if errs:
        print("\n".join(errs)); return 1
    prices = load_prices(a.previous)
    now = W.get_now(a.now)
    fetch = fixture_fetch(a.fixtures) if a.fixtures else searchapi_get
    near = (lambda place: None) if a.fixtures else geocode
    report = {"checked": [], "skipped": [], "searches": 0, "error": None}
    for p in plans:
        if a.plan and p["id"] != a.plan:
            continue
        prev = prices.get(p["id"])
        if not due(p, prev, now, a.every_hours):
            report["skipped"].append(p["id"]); continue
        if report["searches"] >= a.max_searches:
            report["skipped"].append(p["id"] + " (search limit)"); continue
        try:
            rec, used = search_plan(p, prev, now, fetch, near)
        except urllib.error.HTTPError as e:
            report["error"] = f"SearchApi answered HTTP {e.code}." + (
                " " + keys.missing("searchapi", "www.searchapi.io") if e.code in (401, 403) else "")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            blocked = "403" in str(e) or "Tunnel" in str(e)
            report["error"] = ("This run's network does not allow www.searchapi.io. " if blocked else
                               f"Cannot reach SearchApi ({e}). ") + keys.missing("searchapi", "www.searchapi.io")
        if report["error"]:
            # Keep the last good prices; say on the page why this check failed.
            for q in plans:
                if (not a.plan or q["id"] == a.plan) and q.get("status", "watching") == "watching":
                    old = dict(prices.get(q["id"]) or {"planId": q["id"], "history": {}})
                    old.update(lastError=report["error"], lastErrorAt=now.isoformat(timespec="seconds"))
                    prices[q["id"]] = old
            break
        rec.pop("lastError", None); rec.pop("lastErrorAt", None)
        prices[p["id"]] = rec
        report["searches"] += used
        report["checked"].append({"plan": p["id"], "total": rec["total"],
                                  "alerts": [x["title"] for x in plan_alerts(p, rec)]})
    Path(a.out).write_text(json.dumps(prices, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


def cmd_reconcile(a) -> int:
    plans = load_plans(a.plans)
    bookings = load(a.bookings, [])
    bookings = bookings.get("bookings", bookings) if isinstance(bookings, dict) else bookings
    notes = reconcile(plans, bookings)
    Path(a.out or a.plans).write_text(json.dumps({"plans": plans}, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\n".join(notes) if notes else "no plan changes")
    return 0


def cmd_build(a) -> int:
    plans = load_plans(a.plans)
    errs = validate(plans)
    if errs:
        print("\n".join(errs)); return 1
    prices = load_prices(a.prices)
    index = load(a.index, {})
    index = index.get("plans", []) if isinstance(index, dict) else []
    urls = load(a.urls, {}) or {}
    agent = load(a.agent, {}) or {}
    versions = load(a.versions, {}) or {}
    now = W.get_now(a.now)
    out = Path(a.out_dir)
    tpl = Path(a.template) if a.template else Path(__file__).resolve().parent.parent / "dashboard" / "plan.html"
    by_id = {e["id"]: e for e in index}
    result = {"newPlans": [], "plans": []}
    entries = []
    for p in plans:
        rec = prices.get(p["id"])
        page = plan_page(p, rec, now)
        url = (by_id.get(p["id"]) or {}).get("url") or urls.get(p["id"])
        pdir = out / "plans" / p["id"]
        if not url:
            pdir.mkdir(parents=True, exist_ok=True)
            html = W.page_html(tpl.read_text(encoding="utf-8"), f"{p['title']} · plan")
            (pdir / "page.html").write_text(html, encoding="utf-8")
            result["newPlans"].append({"id": p["id"], "page": str((pdir / "page.html").resolve()), "title": p["title"]})
        b = W.Batch(pdir / "docs", (versions.get("plans") or {}).get(p["id"], {}))
        b.add("set", "plan", "data", page)
        tid = agent.get("scannerTriggerId") or agent.get("triggerId")   # "Check prices now" fires this task
        if tid:
            b.add("set", "private", "data", {"agent": {"triggerId": tid}})
        b.save(pdir / "batch.json")
        result["plans"].append({"id": p["id"], "url": url, "batch": str((pdir / "batch.json").resolve()),
                                "alerts": [x["title"] for x in page["alerts"]]})
        entries.append(index_entry(page, url))
    (out / "capabilities-plan.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "capabilities-plan.json").write_text(json.dumps(PLAN_CAPABILITIES), encoding="utf-8")
    hb = W.Batch(out / "home-plans" / "docs", versions.get("home") or {})
    hb.add("set", "index", "plans", {"plans": entries, "updatedAt": now.isoformat(timespec="seconds")})
    hb.add("set", "private", "plans", {"plans": plans, "updatedAt": now.isoformat(timespec="seconds")})
    hb.add("set", "private", "planprices", {"results": prices, "updatedAt": now.isoformat(timespec="seconds")})
    hb.save(out / "home-plans" / "batch.json")
    (out / "plans-result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


def cmd_render_static(a) -> int:
    tpl = (Path(__file__).resolve().parent.parent / "dashboard" / "plan.html").read_text(encoding="utf-8")
    prices, now, out = load_prices(a.prices), W.get_now(a.now), Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for p in load_plans(a.plans):
        page = plan_page(p, prices.get(p["id"]), now)
        blob = json.dumps({"plan": page}, ensure_ascii=False).replace("</", "<\\/")
        body = W.page_html(tpl, p["title"]).replace(
            "<!--WAYFARE_STATIC_DATA-->", f'<script id="wayfare-static" type="application/json">{blob}</script>', 1)
        f = out / f"plan-{p['id']}.html"
        f.write_text(W.STATIC_SKELETON % body, encoding="utf-8")
        written.append(str(f))
    print(json.dumps({"written": written}, indent=1))
    return 0


def cmd_site_bundle(a) -> int:
    """ChatGPT / Codex: one Site project per plan, plus sites/plans-index.json
    that wayfare.py site-bundle puts on Wayfare Home."""
    plans = load_plans(a.plans)
    errs = validate(plans)
    if errs:
        print("\n".join(errs)); return 1
    prices, now = load_prices(a.prices), W.get_now(a.now)
    sites = Path(a.sites_dir); sites.mkdir(parents=True, exist_ok=True)
    urls = load(a.urls, {}) or {}
    root = W.plugin_root()
    template_dir = W._find(root / "site", root.parent / "wayfare" / "site")
    pages_dir = W._find(root / "pages", root / "dashboard")
    shim = (template_dir / "shim.js").read_text(encoding="utf-8")
    tpl = (pages_dir / "plan.html").read_text(encoding="utf-8")
    out = {"sites": []}
    index = []
    for p in plans:
        page = plan_page(p, prices.get(p["id"]), now)
        slug = "plan-" + p["id"]
        d = sites / slug
        changed = W.write_site(d, template_dir, W.site_page(tpl, f"{p['title']} · plan", shim), {"kind": "plan", "plan": page})
        url = urls.get(slug)
        url = url if isinstance(url, str) and url.startswith("https://") else None
        out["sites"].append({"slug": slug, "dir": str(d), "title": f"{p['title']} · plan", "new": not url,
                             "changed": changed, "url": url, "alerts": [x["title"] for x in page["alerts"]]})
        index.append(index_entry(page, url))
    (sites / "plans-index.json").write_text(json.dumps({"plans": index, "updatedAt": now.isoformat(timespec="seconds")},
                                                       indent=1, ensure_ascii=False), encoding="utf-8")
    (sites / "plans-plan.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


def cmd_link(a) -> int:
    p = next((x for x in load_plans(a.plans) if x["id"] == a.plan), None)
    if not p:
        print(f"no plan {a.plan}"); return 1
    links = {}
    for leg in ("out", "back"):
        if (p.get("flights") or {}).get(leg):
            links[leg] = google_flights_url(p, leg)
    if p.get("stay"):
        links["booking"] = booking_url(p); links["googleHotels"] = google_hotels_url(p)
    print(json.dumps(links, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--plans", required=True); v.set_defaults(f=cmd_validate)
    s = sub.add_parser("search")
    s.add_argument("--plans", required=True); s.add_argument("--previous"); s.add_argument("--out", required=True)
    s.add_argument("--plan", help="only this plan id"); s.add_argument("--now")
    s.add_argument("--every-hours", type=float, default=None, help="default: 72 h if the trip is over 60 days away, else 20 h; 0 = now")
    s.add_argument("--max-searches", type=int, default=12); s.add_argument("--fixtures", help=argparse.SUPPRESS)
    s.set_defaults(f=cmd_search)
    r = sub.add_parser("reconcile"); r.add_argument("--plans", required=True); r.add_argument("--bookings", required=True)
    r.add_argument("--out"); r.set_defaults(f=cmd_reconcile)
    b = sub.add_parser("build")
    b.add_argument("--plans", required=True); b.add_argument("--prices")
    b.add_argument("--index"); b.add_argument("--urls"); b.add_argument("--versions"); b.add_argument("--now")
    b.add_argument("--agent", help="Home private/agent (for the Check prices now button)")
    b.add_argument("--template"); b.add_argument("--out-dir", required=True); b.set_defaults(f=cmd_build)
    rs = sub.add_parser("render-static", help="standalone HTML per plan, for testing")
    rs.add_argument("--plans", required=True); rs.add_argument("--prices"); rs.add_argument("--now")
    rs.add_argument("--out-dir", required=True); rs.set_defaults(f=cmd_render_static)
    sb = sub.add_parser("site-bundle", help="ChatGPT/Codex: one Site project per plan")
    sb.add_argument("--plans", required=True); sb.add_argument("--prices"); sb.add_argument("--now")
    sb.add_argument("--sites-dir", required=True); sb.add_argument("--urls"); sb.set_defaults(f=cmd_site_bundle)
    k = sub.add_parser("link"); k.add_argument("--plans", required=True); k.add_argument("--plan", required=True)
    k.set_defaults(f=cmd_link)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
