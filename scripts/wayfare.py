#!/usr/bin/env python3
"""Wayfare trip engine.

Pure standard library. Claude extracts bookings from email; this script does
the parts that must be exact and repeatable:

  * validate the extracted bookings,
  * group bookings into trips,
  * find unbooked nights, tight connections, schedule-change ripples,
    double bookings and fare drops,
  * produce the dashboard data, with booking codes and prices removed from
    everything that a shared viewer can read.

Commands
  validate       Check a bookings file and print problems.
  merge          Merge newly extracted bookings into the stored list.
  build          Build one batch per trip page, page files for new trips,
                 and the pending home index.
  home-batch     After new trip pages are published, write the home batch
                 with their links.
  capabilities   Print the runtime capabilities for a trip or home page.
  render-static  Write standalone HTML pages (for Claude Code in a terminal,
                 or for local testing).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from urllib.parse import urlencode
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ENGINE_VERSION = "0.6.0"
TRANSPORT = {"flight", "train", "transfer"}
TYPES = TRANSPORT | {"hotel", "dining", "other"}
STATUSES = {"confirmed", "changed", "cancelled"}
DEFAULT_PROFILE = {
    "homeAirports": [],
    "homeCity": "",
    "minConnectionMinutes": 75,
    "arrivalToDinnerMinutes": 150,
    "fareDropMinimum": 25,
    "delayAlertMinutes": 20,
}
STATUS_MAX_AGE_HOURS = 18
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ----------------------------------------------------------------- helpers

def parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 date-time that MUST carry a UTC offset."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"time '{value}' has no UTC offset (example: 2026-11-06T07:05:00+01:00)")
    return dt


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def day_label(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def time_label(dt: datetime) -> str:
    return f"{day_label(dt.date())} · {dt.strftime('%H:%M')}"


def range_label(a: date, b: date) -> str:
    if a.month == b.month and a.year == b.year:
        return f"{a.day}–{b.day} {MONTHS[a.month - 1]} {a.year}"
    return f"{a.day} {MONTHS[a.month - 1]} – {b.day} {MONTHS[b.month - 1]} {b.year}"


def mask_code(code: str | None) -> str | None:
    """Keep only the last 2 characters. A booking code plus a surname is
    enough to change or cancel a flight, so shared views never get it."""
    if not code:
        return None
    code = str(code).strip()
    if len(code) <= 2:
        return "••"
    return "••••" + code[-2:]


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "trip"


def norm(text: str | None) -> str:
    return (text or "").strip().lower()


def minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


# ----------------------------------------------------------------- model

@dataclass
class Item:
    raw: dict
    type: str
    start: datetime          # aware; for hotels: check-in date at 00:00 local (naive offset unknown -> UTC)
    end: datetime
    start_date: date         # local calendar date at the place it starts
    end_date: date           # local calendar date at the place it ends
    city_from: str = ""
    city_to: str = ""
    live: dict | None = None     # live flight status, see apply_status()

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def status(self) -> str:
        return self.raw.get("status", "confirmed")


@dataclass
class Trip:
    items: list[Item] = field(default_factory=list)
    closed: bool = False

    @property
    def start(self) -> datetime:
        return min(i.start for i in self.items)

    @property
    def end(self) -> datetime:
        return max(i.end for i in self.items)


# ----------------------------------------------------------------- validation

def validate_booking(b: Any, idx: int) -> list[str]:
    where = f"booking[{idx}]"
    if not isinstance(b, dict):
        return [f"{where}: must be an object"]
    errs: list[str] = []
    where = f"booking[{idx}] ({b.get('id', '?')})"
    if not b.get("id"):
        errs.append(f"{where}: missing 'id'")
    t = b.get("type")
    if t not in TYPES:
        errs.append(f"{where}: 'type' must be one of {sorted(TYPES)}")
        return errs
    if b.get("status", "confirmed") not in STATUSES:
        errs.append(f"{where}: 'status' must be one of {sorted(STATUSES)}")
    price = b.get("price")
    if price is not None:
        if not isinstance(price, dict) or not isinstance(price.get("amount"), (int, float)) or not price.get("currency"):
            errs.append(f"{where}: 'price' must be {{amount: number, currency: 'EUR'}}")
    if b.get("manageUrl") and not str(b["manageUrl"]).startswith("https://"):
        errs.append(f"{where}: manageUrl must start with https://")
    def need_dt(key: str) -> None:
        if not b.get(key):
            errs.append(f"{where}: missing '{key}'")
            return
        try:
            parse_dt(b[key])
        except ValueError as e:
            errs.append(f"{where}: {key}: {e}")
    if t in TRANSPORT:
        need_dt("depart"); need_dt("arrive")
        if t == "flight":
            for k in ("from", "to"):
                v = b.get(k, "")
                if not re.fullmatch(r"[A-Z]{3}", str(v)):
                    errs.append(f"{where}: '{k}' must be a 3-letter IATA airport code")
        else:
            for k in ("from", "to"):
                if not b.get(k):
                    errs.append(f"{where}: missing '{k}'")
        if not errs and parse_dt(b["arrive"]) < parse_dt(b["depart"]):
            errs.append(f"{where}: arrive is before depart")
        prev = b.get("previous")
        if prev is not None:
            for k in ("depart", "arrive"):
                if k in prev:
                    try:
                        parse_dt(prev[k])
                    except ValueError as e:
                        errs.append(f"{where}: previous.{k}: {e}")
    elif t == "hotel":
        for k in ("name", "city", "checkIn", "checkOut"):
            if not b.get(k):
                errs.append(f"{where}: missing '{k}'")
        try:
            if parse_date(b["checkOut"]) <= parse_date(b["checkIn"]):
                errs.append(f"{where}: checkOut must be after checkIn")
        except (KeyError, ValueError, TypeError):
            errs.append(f"{where}: checkIn/checkOut must be YYYY-MM-DD")
        lc = b.get("latestCheckIn")
        if lc and not re.fullmatch(r"\d{2}:\d{2}", lc):
            errs.append(f"{where}: latestCheckIn must be HH:MM")
    elif t in ("dining", "other"):
        need_dt("start")
        if b.get("end"):
            need_dt("end")
        if not b.get("name"):
            errs.append(f"{where}: missing 'name'")
    return errs


def validate(bookings: Any) -> list[str]:
    if not isinstance(bookings, list):
        return ["bookings file must contain a JSON array"]
    errs: list[str] = []
    seen: set[str] = set()
    for i, b in enumerate(bookings):
        errs += validate_booking(b, i)
        bid = b.get("id") if isinstance(b, dict) else None
        if bid in seen:
            errs.append(f"booking[{i}]: duplicate id '{bid}'")
        seen.add(bid)
    return errs


# ----------------------------------------------------------------- items

def to_item(b: dict) -> Item:
    t = b["type"]
    if t in TRANSPORT:
        dep, arr = parse_dt(b["depart"]), parse_dt(b["arrive"])
        return Item(b, t, dep, arr, dep.date(), arr.date(),
                    b.get("fromCity") or b.get("from", ""), b.get("toCity") or b.get("to", ""))
    if t == "hotel":
        ci, co = parse_date(b["checkIn"]), parse_date(b["checkOut"])
        # Hotels carry dates only. Use 15:00 / 11:00 UTC as neutral anchors for ordering.
        s = datetime(ci.year, ci.month, ci.day, 15, tzinfo=timezone.utc)
        e = datetime(co.year, co.month, co.day, 11, tzinfo=timezone.utc)
        return Item(b, t, s, e, ci, co, b["city"], b["city"])
    s = parse_dt(b["start"])
    e = parse_dt(b["end"]) if b.get("end") else s + timedelta(hours=2)
    return Item(b, t, s, e, s.date(), e.date(), b.get("city", ""), b.get("city", ""))


def fr24_url(raw: dict) -> str:
    return "https://www.flightradar24.com/data/flights/" + f"{raw.get('carrier', '')}{raw.get('flightNumber', '')}".lower()


def _wall_to_aware(wall: str | None, like: datetime) -> datetime | None:
    """A local wall-clock time 'YYYY-MM-DDTHH:MM' in the time zone of `like`."""
    if not wall:
        return None
    try:
        return datetime.fromisoformat(wall[:16]).replace(tzinfo=like.tzinfo)
    except ValueError:
        return None


def apply_status(items: list[Item], status: dict[str, dict], now: datetime, prof: dict) -> None:
    """Use recent live flight status: move the item to the expected times, so
    the normal checks (connections, dinners, hotel check-in) see knock-on
    effects. The booked times stay in item.raw."""
    for it in items:
        rec = status.get(it.id)
        if it.type != "flight" or not rec:
            continue
        try:
            age = now - parse_dt(rec["checkedAt"])
        except (KeyError, ValueError):
            continue
        if age > timedelta(hours=STATUS_MAX_AGE_HOURS) or rec.get("flightDate") not in (None, it.raw["depart"][:10]):
            continue
        state = rec.get("state") or "scheduled"
        dep_b, arr_b = it.start, it.end
        sched = _wall_to_aware(rec.get("depScheduled"), dep_b)
        dep = _wall_to_aware(rec.get("depActual") or rec.get("depEstimated"), dep_b) or sched or dep_b
        arr = _wall_to_aware(rec.get("arrActual") or rec.get("arrEstimated"), arr_b)
        if arr is None:
            arr_s = _wall_to_aware(rec.get("arrScheduled"), arr_b) or arr_b
            arr = arr_s + max(timedelta(0), dep - (sched or dep_b))
        delay = minutes(dep - dep_b)
        arr_delay = minutes(arr - arr_b)
        if state != "cancelled" and abs(delay) < 24 * 60 and abs(arr_delay) < 24 * 60:
            it.start, it.end = dep, arr
            it.start_date, it.end_date = dep.date(), arr.date()
        if state == "cancelled":
            label = "Cancelled"
        elif state == "diverted":
            label = "Diverted"
        elif state == "landed":
            label = f"Landed {arr.strftime('%H:%M')}"
        elif state in ("active", "incident"):
            label = "In the air" + (f", {delay} min late" if delay >= prof["delayAlertMinutes"] else "")
        elif delay >= 5:
            label = f"{delay} min late"
        elif delay <= -5:
            label = f"{-delay} min early"
        else:
            label = "On time"
        it.live = {
            "state": state, "label": label, "delay": delay, "arrDelay": arr_delay,
            "depTime": dep.strftime("%H:%M"), "arrTime": arr.strftime("%H:%M"),
            "depTerminal": rec.get("depTerminal"), "depGate": rec.get("depGate"),
            "arrTerminal": rec.get("arrTerminal"), "arrGate": rec.get("arrGate"), "baggage": rec.get("baggage"),
            "checkedAt": rec["checkedAt"], "source": rec.get("source") or "flight status",
        }


def is_home_departure(it: Item, prof: dict) -> bool:
    if it.type == "flight" and it.raw.get("from") in prof["homeAirports"]:
        return True
    return it.type in TRANSPORT and bool(prof["homeCity"]) and norm(it.city_from) == norm(prof["homeCity"])


def is_home_arrival(it: Item, prof: dict) -> bool:
    if it.type == "flight" and it.raw.get("to") in prof["homeAirports"]:
        return True
    return it.type in TRANSPORT and bool(prof["homeCity"]) and norm(it.city_to) == norm(prof["homeCity"])


def group_trips(items: list[Item], prof: dict) -> list[Trip]:
    """Home-based grouping: leaving home opens a trip, coming home closes it.
    Without a home airport or city, a gap of more than 4 days starts a new trip."""
    items = sorted(items, key=lambda i: (i.start, i.end))
    has_home = bool(prof["homeAirports"] or prof["homeCity"])
    trips: list[Trip] = []
    cur: Trip | None = None
    for it in items:
        if cur is None:
            cur = Trip(); trips.append(cur)
        elif has_home:
            if cur.closed or (is_home_departure(it, prof) and len(cur.items) > 0 and
                              any(is_home_departure(x, prof) for x in cur.items)):
                cur = Trip(); trips.append(cur)
        else:
            if it.start - cur.end > timedelta(days=4):
                cur = Trip(); trips.append(cur)
        cur.items.append(it)
        if has_home and is_home_arrival(it, prof) and len(cur.items) > 0:
            cur.closed = True
    return trips


# ----------------------------------------------------------------- analysis

def trip_city(trip: Trip, prof: dict) -> str:
    counts: dict[str, int] = {}
    for it in trip.items:
        if it.type == "hotel":
            counts[it.city_to] = counts.get(it.city_to, 0) + (it.end_date - it.start_date).days
    if counts:
        return max(counts, key=counts.get)
    for it in trip.items:
        if it.type in TRANSPORT and not is_home_arrival(it, prof):
            return it.city_to
    return trip.items[0].city_to or "Trip"


def trip_cities(trip: Trip, prof: dict) -> list[str]:
    """Places you stay: hotel cities, plus arrivals not followed by another
    departure within 12 hours (so a connection city is not a destination)."""
    seen: list[str] = []
    items = sorted(trip.items, key=lambda i: i.start)
    transport = [i for i in items if i.type in TRANSPORT]
    for it in items:
        c = ""
        if it.type == "hotel":
            c = it.city_to
        elif it.type in TRANSPORT and not is_home_arrival(it, prof):
            nxt = next((t for t in transport if t.start >= it.end), None)
            if nxt is None or nxt.start - it.end > timedelta(hours=12):
                c = it.city_to
        if c and norm(c) != norm(prof["homeCity"]) and c not in seen:
            seen.append(c)
    return seen


def lodging_gaps(trip: Trip, prof: dict) -> list[dict]:
    transport = [i for i in trip.items if i.type in TRANSPORT]
    if not transport:
        return []
    first_arrival = next((i for i in transport if not is_home_arrival(i, prof)), transport[0])
    first_night = first_arrival.end_date
    home_back = [i for i in transport if is_home_arrival(i, prof)]
    if home_back:
        last_day = home_back[-1].start_date
    else:
        last_day = max(i.end_date for i in trip.items)
    nights = []
    d = first_night
    while d < last_day:
        covered = False
        for it in trip.items:
            if it.type == "hotel" and it.start_date <= d < it.end_date:
                covered = True; break
            if it.type in TRANSPORT and it.start_date <= d < it.end_date:
                covered = True; break  # overnight in transit
        if not covered:
            nights.append(d)
        d += timedelta(days=1)
    # group consecutive nights and find the city for each group
    gaps: list[dict] = []
    for n in nights:
        if gaps and gaps[-1]["_last"] + timedelta(days=1) == n:
            gaps[-1]["_last"] = n
        else:
            gaps.append({"_first": n, "_last": n})
    out = []
    for g in gaps:
        city = ""
        anchor = datetime(g["_first"].year, g["_first"].month, g["_first"].day, 23, tzinfo=timezone.utc)
        for it in sorted(trip.items, key=lambda i: i.end):
            if it.end <= anchor or it.end_date <= g["_first"]:
                city = it.city_to or city
        n_nights = (g["_last"] - g["_first"]).days + 1
        out.append({
            "kind": "lodging",
            "city": city,
            "firstNight": g["_first"].isoformat(),
            "lastNight": g["_last"].isoformat(),
            "nights": n_nights,
            "label": f"{n_nights} night{'s' if n_nights != 1 else ''} with no stay booked"
                     f"{' in ' + city if city else ''} · {range_label(g['_first'], g['_last'] + timedelta(days=1))}",
        })
    return out


def trip_nights(trip: Trip, prof: dict) -> list[dict]:
    """Every night of the trip: where you sleep, in transit, or nothing booked.
    Same bounds as lodging_gaps."""
    transport = sorted([i for i in trip.items if i.type in TRANSPORT], key=lambda i: i.start)
    if not transport:
        hotels = [i for i in trip.items if i.type == "hotel"]
        if not hotels:
            return []
        first, last = min(h.start_date for h in hotels), max(h.end_date for h in hotels)
    else:
        first = next((i for i in transport if not is_home_arrival(i, prof)), transport[0]).end_date
        back = [i for i in transport if is_home_arrival(i, prof)]
        last = back[-1].start_date if back else max(i.end_date for i in trip.items)
    out = []
    d = first
    city = ""
    while d < last:
        night = {"date": d.isoformat(), "label": day_label(d), "kind": "gap", "city": "", "stay": None, "itemId": None}
        for it in sorted(trip.items, key=lambda i: i.start):
            if it.type in TRANSPORT and it.end_date <= d:
                city = it.city_to or city
        hotel = next((h for h in trip.items if h.type == "hotel" and h.start_date <= d < h.end_date), None)
        moving = next((t for t in transport if t.start_date <= d < t.end_date), None)
        if hotel:
            city = hotel.city_to
            night.update(kind="stay", city=hotel.city_to, stay=hotel.raw["name"], itemId=hotel.id)
        elif moving:
            night.update(kind="transit", city="", stay=title_of(moving), itemId=moving.id)
        else:
            night["city"] = city
        out.append(night)
        d += timedelta(days=1)
    return out


def day_cities(trip: Trip, prof: dict, nights: list[dict]) -> list[tuple[str, str]]:
    """(date, city) for each day you are away: the city of that night, and on
    the last day the city you leave from."""
    by_id = {i.id: i for i in trip.items}
    out: list[tuple[str, str]] = []
    last = ""
    for n in nights:
        c = n["city"]
        if not c and n.get("itemId") in by_id:
            c = by_id[n["itemId"]].city_to
        c = c or last
        if c:
            out.append((n["date"], c))
            last = c
    if nights and last:
        end = (parse_date(nights[-1]["date"]) + timedelta(days=1)).isoformat()
        out.append((end, last))
    if not out:                      # day trip
        away = [i for i in trip.items if not is_home_arrival(i, prof)]
        if away:
            out.append((away[0].start_date.isoformat(), away[0].city_to))
    return out


def first_per_city(days_wx: list[dict], today: str, n: int = 2) -> list[dict] | None:
    """For Wayfare Home: the first coming day in each city (at most n cities)."""
    out, seen = [], set()
    for w in days_wx:
        if w["date"] >= today and w["city"] not in seen:
            out.append(w); seen.add(w["city"])
    return out[:n] or None


def day_routes(trip: Trip, prof: dict) -> dict[str, str]:
    """A Google Maps route for each day: the places you go on the ground
    (a flight splits the day; the part with the most places wins)."""
    segs_by_day: dict[str, list[list[str]]] = {}
    for it in sorted(trip.items, key=lambda i: display_key(i, trip.items)):
        r = it.raw
        segs = segs_by_day.setdefault(it.start_date.isoformat(), [[]])

        def add(p: str) -> None:
            if not segs[-1] or segs[-1][-1] != p:
                segs[-1].append(p)
        if it.type == "flight":
            add(f"{r.get('from')} airport")
            segs.append([f"{r.get('to')} airport"])
        elif it.type in ("train", "transfer"):
            for p in (r.get("from") or it.city_from, r.get("to") or it.city_to):
                add(p if it.type != "train" or "station" in p.lower() else f"{p} station")
        elif it.type == "hotel":
            add(f"{r['name']}, {r['city']}")
        else:
            add(f"{r['name']}, {r.get('city', '')}".strip(", "))
    out = {}
    for d, segs in segs_by_day.items():
        best = max(reversed(segs), key=len)
        if len(best) >= 2:
            q = {"api": 1, "origin": best[0], "destination": best[-1]}
            if len(best) > 2:
                q["waypoints"] = "|".join(best[1:-1][:8])
            out[d] = "https://www.google.com/maps/dir/?" + urlencode(q)
    return out


def trip_route(trip: Trip, prof: dict, nights: list[dict]) -> list[dict]:
    """The journey as places: start, each city you sleep in (with nights and
    unbooked nights), and the way back. `mode` is how you arrive there."""
    transport = sorted([i for i in trip.items if i.type in TRANSPORT], key=lambda i: i.start)
    stops: list[dict] = []
    for n in nights:
        if n["kind"] == "transit":
            continue
        c = n["city"] or "?"
        if stops and stops[-1]["city"] == c:
            stops[-1]["nights"] += 1
            stops[-1]["unbooked"] += n["kind"] == "gap"
            stops[-1]["to"] = n["date"]
        else:
            stops.append({"city": c, "nights": 1, "unbooked": int(n["kind"] == "gap"), "from": n["date"], "to": n["date"]})
    for s in stops:
        arriving = [t for t in transport if norm(t.city_to) == norm(s["city"]) and t.end_date.isoformat() <= s["from"]]
        s["mode"] = arriving[-1].type if arriving else None
    route: list[dict] = []
    if transport:
        route.append({"city": transport[0].city_from, "kind": "start"})
    route += [dict(s, kind="stay") for s in stops]
    if transport and is_home_arrival(transport[-1], prof):
        route.append({"city": transport[-1].city_to, "kind": "end", "mode": transport[-1].type})
    return route


def alert(level: str, kind: str, title: str, detail: str, item_ids: list[str]) -> dict:
    return {"level": level, "kind": kind, "title": title, "detail": detail, "itemIds": item_ids}


def find_alerts(trip: Trip, prof: dict, fares: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    items = sorted(trip.items, key=lambda i: i.start)
    transport = [i for i in items if i.type in TRANSPORT]
    changed_ids = {i.id for i in items if i.status == "changed" or (i.live and i.live["state"] != "cancelled"
                                                                    and max(i.live["delay"], i.live["arrDelay"]) >= prof["delayAlertMinutes"])}

    # 1. schedule changes
    for it in items:
        if it.status == "changed" and it.raw.get("previous"):
            p = it.raw["previous"]
            parts = []
            if p.get("depart"):
                parts.append(f"departs {parse_dt(p['depart']).strftime('%H:%M')} → {parse_dt(it.raw['depart']).strftime('%H:%M')}")
            if p.get("arrive"):
                parts.append(f"arrives {parse_dt(p['arrive']).strftime('%H:%M')} → {parse_dt(it.raw['arrive']).strftime('%H:%M')}")
            out.append(alert("high", "schedule_change", f"Schedule changed: {title_of(it)}",
                             "; ".join(parts) + ". Check what this affects below.", [it.id]))

    # 1b. live flight status (see apply_status)
    for it in items:
        lv = it.live
        if not lv:
            continue
        name = title_of(it)
        when = f"checked {lv['checkedAt'][11:16]} UTC via {lv['source']}"
        if lv["state"] == "cancelled":
            out.append(alert("high", "flight_cancelled", f"{name} is cancelled",
                             f"The flight status shows {name} as cancelled ({when}). Check your email and the airline "
                             "app for a new flight before you go to the airport.", [it.id]))
        elif lv["state"] == "diverted":
            out.append(alert("high", "flight_diverted", f"{name} is diverted",
                             f"{name} is going to another airport ({when}). Follow the airline's instructions.", [it.id]))
        elif lv["delay"] >= prof["delayAlertMinutes"] or lv["arrDelay"] >= prof["delayAlertMinutes"]:
            late = max(lv["delay"], lv["arrDelay"])
            out.append(alert("high" if late >= 120 else "medium", "flight_delayed", f"{name} is late",
                             f"About {late} min late: now departs {lv['depTime']} (booked {parse_dt(it.raw['depart']).strftime('%H:%M')}), "
                             f"arrives {lv['arrTime']} ({when}). Check what this affects below.", [it.id]))

    # 2. tight or impossible connections
    for a, b in zip(transport, transport[1:]):
        gap = minutes(b.start - a.end)
        if gap > 12 * 60:
            continue
        if gap < 0:
            out.append(alert("high", "overlap", "Next departure is before you arrive",
                             f"{title_of(a)} arrives {a.end.strftime('%H:%M')}, but {title_of(b)} leaves "
                             f"{b.start.strftime('%H:%M')}.", [a.id, b.id]))
        elif gap < prof["minConnectionMinutes"]:
            out.append(alert("high", "tight_connection", f"Only {gap} min to connect",
                             f"{title_of(a)} → {title_of(b)}. Your minimum is {prof['minConnectionMinutes']} min.",
                             [a.id, b.id]))

    # 3. arrival vs dinner reservations
    for d in (i for i in items if i.type == "dining"):
        arrivals = [t for t in transport if t.start <= d.start and minutes(d.start - t.end) < 12 * 60]
        landing_after = [t for t in transport if t.start < d.start < t.end]
        if landing_after:
            t = landing_after[0]
            out.append(alert("high", "dining_conflict", f"You are still travelling at {d.raw['name']}",
                             f"Table at {d.start.strftime('%H:%M')}, but {title_of(t)} arrives {t.end.strftime('%H:%M')}.",
                             [t.id, d.id]))
            continue
        if arrivals:
            t = max(arrivals, key=lambda x: x.end)
            gap = minutes(d.start - t.end)
            if gap < prof["arrivalToDinnerMinutes"]:
                out.append(alert("medium", "tight_dining", f"{gap} min from arrival to {d.raw['name']}",
                                 f"{title_of(t)} arrives {t.end.strftime('%H:%M')}, table at {d.start.strftime('%H:%M')}. "
                                 f"Your buffer is {prof['arrivalToDinnerMinutes']} min.", [t.id, d.id]))

    # 4. hotels: arrival after check-in day, or after latest check-in time
    hotels = [i for i in items if i.type == "hotel"]
    for h in hotels:
        into = [t for t in transport if norm(t.city_to) == norm(h.city_to) and t.end_date <= h.start_date + timedelta(days=1)
                and t.start_date >= h.start_date - timedelta(days=2)]
        if not into:
            continue
        t = max(into, key=lambda x: x.end)
        if t.end_date > h.start_date:
            out.append(alert("high", "no_show_risk", f"You arrive after your check-in day at {h.raw['name']}",
                             f"Check-in is {day_label(h.start_date)}, but {title_of(t)} arrives {time_label(t.end)}. "
                             "Tell the hotel, or it may cancel the stay as a no-show.", [t.id, h.id]))
        elif h.raw.get("latestCheckIn") and t.end_date == h.start_date and t.end.strftime("%H:%M") > h.raw["latestCheckIn"]:
            out.append(alert("high", "late_checkin", f"Late arrival at {h.raw['name']}",
                             f"{title_of(t)} arrives {t.end.strftime('%H:%M')}; latest check-in is {h.raw['latestCheckIn']}.",
                             [t.id, h.id]))

    # 5. two stays on the same night
    for i, a in enumerate(hotels):
        for b in hotels[i + 1:]:
            first = max(a.start_date, b.start_date)
            last = min(a.end_date, b.end_date)
            if first < last:
                n = (last - first).days
                out.append(alert("medium", "double_booking", f"Two stays booked for {n} night{'s' if n > 1 else ''}",
                                 f"{a.raw['name']} and {b.raw['name']} overlap from {day_label(first)}. "
                                 "If this is a mistake, cancel one while it is still free to cancel.", [a.id, b.id]))

    # 6. fare drops (from fare_check.py results)
    for it in transport:
        f = fares.get(it.id)
        if not f:
            continue
        drop = round(f["paidPerTraveler"] - f["livePerTraveler"], 2)
        if drop >= prof["fareDropMinimum"]:
            trav = int(it.raw.get("travelers") or 1)
            out.append(alert("info", "fare_drop", f"Fare is {f['currency']} {drop:.0f} lower per traveller",
                             f"{title_of(it)}: you paid about {f['currency']} {f['paidPerTraveler']:.0f} per traveller, a fare now shows "
                             f"{f['currency']} {f['livePerTraveler']:.0f} (checked {f['checkedAt'][:16].replace('T', ' ')} UTC, "
                             f"via {f.get('source', 'fare search')}). Up to {f['currency']} {drop * trav:.0f} for "
                             f"{trav} traveller{'s' if trav > 1 else ''}. Whether you can claim it depends on your "
                             "fare rules; open your booking on the airline site to check.", [it.id]))

    # Mark alerts that are a consequence of a schedule change
    for a in out:
        if a["kind"] != "schedule_change" and changed_ids.intersection(a["itemIds"]):
            a["fromChange"] = True
    order = {"high": 0, "medium": 1, "info": 2}
    out.sort(key=lambda a: order[a["level"]])
    return out


def title_of(it: Item) -> str:
    r = it.raw
    if it.type == "flight":
        return f"{r.get('carrier', '')} {r.get('flightNumber', '')}".strip() or f"{r['from']}→{r['to']}"
    if it.type in ("train", "transfer"):
        return r.get("name") or f"{it.type.title()} {it.city_from} → {it.city_to}"
    return r.get("name", it.type.title())


# ----------------------------------------------------------------- links and alert identity

def maps_url(query: str) -> str:
    return "https://www.google.com/maps/search/?api=1&" + urlencode({"query": query})


def search_url(query: str) -> str:
    return "https://www.google.com/search?" + urlencode({"q": query})


def stays_search_url(city: str, check_in: str, check_out: str, guests: int) -> str:
    return "https://www.booking.com/searchresults.html?" + urlencode(
        {"ss": city, "checkin": check_in, "checkout": check_out, "group_adults": guests, "no_rooms": 1})


def provider_of(raw: dict) -> str:
    return raw.get("bookedVia") or raw.get("provider") or ""


def manage_link(raw: dict) -> dict | None:
    """A shared-safe link: a search for the provider's manage-booking page.
    The direct link from the email (manageUrl) can carry a login token, so
    it stays in the owner-only data."""
    p = provider_of(raw)
    if not p:
        return None
    return {"label": f"Manage booking · {p}", "url": search_url(f"{p} manage booking")}


def short_hash(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def enrich_alert(a: dict, by_id: dict[str, Item], travellers: int) -> dict:
    """Add a stable id, a fingerprint, links and an optional Ask-Claude request."""
    key = a.get("key", "")
    a["id"] = f"{a['kind']}-{short_hash(a['kind'] + '|' + '|'.join(sorted(a['itemIds'])) + '|' + key)}"
    volatile = a["kind"] in ("fare_drop", "flight_delayed")
    fp_text = a["title"] + ("" if volatile else "|" + a["detail"])
    a["fingerprint"] = short_hash(fp_text, 10)
    links: list[dict] = []
    items = [by_id[i] for i in a["itemIds"] if i in by_id]
    if a["kind"] == "lodging_gap":
        g = a["gap"]
        check_out = (parse_date(g["lastNight"]) + timedelta(days=1)).isoformat()
        links.append({"label": f"Search stays in {g['city']}" if g["city"] else "Search stays",
                      "url": stays_search_url(g["city"], g["firstNight"], check_out, travellers)})
        if g["city"]:
            links.append({"label": "Hotels on the map", "url": maps_url(f"hotels in {g['city']}")})
        a["ask"] = {"kind": "find-stays", "label": "Ask Claude for stays", "city": g["city"],
                    "checkIn": g["firstNight"], "checkOut": check_out, "guests": travellers}
    else:
        for it in items:
            if it.type in ("hotel", "dining"):
                links.append({"label": f"{it.raw.get('name')} on the map", "url": maps_url(f"{it.raw.get('name')} {it.raw.get('city', '')}")})
            m = manage_link(it.raw)
            if m and m["url"] not in {l["url"] for l in links}:
                links.append(m)
    a["links"] = links[:4]
    # The card the alert is shown on: the last item it names (the dinner you
    # may miss, the second flight of a tight connection, the hotel you reach late).
    a["anchor"] = a["itemIds"][-1] if a["itemIds"] else None
    a["primary"] = primary_action(a, by_id)
    return a


PRIMARY_LABEL = {
    "schedule_change": "Check the new time", "tight_connection": "Manage booking", "overlap": "Manage booking",
    "tight_dining": "Change table time", "dining_conflict": "Change table time", "double_booking": "Manage booking",
    "fare_drop": "Check the fare", "no_show_risk": "Contact the hotel", "late_checkin": "Contact the hotel",
    "flight_cancelled": "Rebook with the airline", "flight_diverted": "Live flight status", "flight_delayed": "Live flight status",
}


def primary_action(a: dict, by_id: dict[str, Item]) -> dict | None:
    """The one action shown on the card. `manage: true` lets the owner's page
    swap in the direct manage-booking link from the email."""
    if a["kind"] == "lodging_gap":
        return {"label": "Search stays", "url": a["links"][0]["url"]} if a["links"] else None
    it = by_id.get(a.get("anchor") or "")
    if not it:
        return None
    label = PRIMARY_LABEL.get(a["kind"], "Manage booking")
    if a["kind"] in ("flight_delayed", "flight_diverted"):
        return {"label": label, "url": fr24_url(it.raw), "itemId": it.id, "manage": False}
    if a["kind"] in ("no_show_risk", "late_checkin"):
        return {"label": label, "url": maps_url(f"{it.raw.get('name')} {it.raw.get('city', '')}"), "itemId": it.id, "manage": False}
    m = manage_link(it.raw)
    if not m:
        return None
    return {"label": label, "url": m["url"], "itemId": it.id, "manage": True}


# ----------------------------------------------------------------- output

def display_key(it: Item, items: list[Item]) -> datetime:
    """Timeline order. A hotel has only a date, so show it just after the
    transport that brings you to its city that day."""
    if it.type != "hotel":
        return it.start
    arrivals = [t.end for t in items if t.type in TRANSPORT and norm(t.city_to) == norm(it.city_to)
                and t.end_date == it.start_date]
    return max(arrivals) + timedelta(minutes=1) if arrivals else it.start


def public_item(it: Item) -> dict:
    """Shared-safe view of a booking: no prices, no full codes, no notes, no manage links."""
    r = it.raw
    if it.type in TRANSPORT:      # show the booked times; live times go in "live"
        it = Item(r, it.type, parse_dt(r["depart"]), parse_dt(r["arrive"]), parse_dt(r["depart"]).date(),
                  parse_dt(r["arrive"]).date(), it.city_from, it.city_to, it.live)
    base = {"id": it.id, "type": it.type, "status": it.status, "code": mask_code(r.get("confirmation")),
            "day": it.start_date.isoformat(), "dayLabel": day_label(it.start_date),
            "time": it.start.strftime("%H:%M") if it.type != "hotel" else (r.get("checkInFrom") or "Check-in"),
            "endTime": it.end.strftime("%H:%M") if it.type in TRANSPORT else None,
            "endDayOffset": (it.end_date - it.start_date).days if it.type in TRANSPORT else 0,
            "travellers": int(r.get("travelers") or r.get("partySize") or 1),
            "operator": r.get("provider") or "",
            "links": []}
    if it.type == "flight":
        base.update({"fromCode": r.get("from"), "toCode": r.get("to"), "fromName": it.city_from, "toName": it.city_to,
                     "number": f"{r.get('carrier', '')} {r.get('flightNumber', '')}".strip(), "cabin": r.get("cabin") or ""})
        if r.get("carrier") and r.get("flightNumber"):
            base["links"].append({"label": "Live flight status", "url": fr24_url(r)})
        if it.live:
            base["live"] = it.live
    elif it.type in ("train", "transfer"):
        base.update({"fromName": r.get("from") or it.city_from, "toName": r.get("to") or it.city_to,
                     "fromCity": it.city_from, "toCity": it.city_to, "number": r.get("name") or ""})
    elif it.type == "hotel":
        base.update({"nights": (it.end_date - it.start_date).days, "checkInLabel": day_label(it.start_date),
                     "checkOutLabel": day_label(it.end_date), "city": r.get("city", "")})
    else:
        base.update({"party": r.get("partySize"), "city": r.get("city", "")})
    if it.type in TRANSPORT:
        route = f"{r.get('from', '')} → {r.get('to', '')}" if it.type == "flight" else f"{it.city_from} → {it.city_to}"
        sub = [s for s in [r.get("provider"), f"{r.get('carrier', '')} {r.get('flightNumber', '')}".strip() if it.type == "flight" else r.get("name"),
                           r.get("cabin"), f"{r['travelers']} travellers" if (r.get("travelers") or 1) > 1 else None] if s]
        base.update({
            "title": f"{it.city_from} → {it.city_to}",
            "route": route,
            "subtitle": " · ".join(sub),
            "when": time_label(it.start),
            "until": time_label(it.end) if it.end_date != it.start_date else it.end.strftime("%H:%M"),
            "calendar": {"summary": f"{title_of(it)} {route}", "start": r["depart"], "end": r["arrive"],
                         "location": r.get("from") if it.type == "flight" else r.get("from", "")},
        })
        if it.status == "changed" and r.get("previous"):
            p = r["previous"]
            base["previous"] = {k: time_label(parse_dt(v)) for k, v in p.items() if k in ("depart", "arrive")}
    elif it.type == "hotel":
        n = (it.end_date - it.start_date).days
        base.update({
            "title": r["name"],
            "subtitle": " · ".join(s for s in [r["city"], r.get("provider"), f"{r['travelers']} guests" if (r.get("travelers") or 1) > 1 else None] if s),
            "when": f"{day_label(it.start_date)} → {day_label(it.end_date)}",
            "until": f"{n} night{'s' if n != 1 else ''}",
            "calendar": {"summary": f"Stay: {r['name']}", "allDay": True, "start": r["checkIn"], "end": r["checkOut"],
                         "location": f"{r['name']}, {r['city']}"},
        })
        base["links"].append({"label": "Map", "url": maps_url(f"{r['name']} {r['city']}")})
    else:
        base.update({
            "title": r["name"],
            "subtitle": " · ".join(s for s in [r.get("city"), r.get("provider"), f"Table for {r['partySize']}" if r.get("partySize") else None] if s),
            "when": time_label(it.start),
            "until": "",
            "calendar": {"summary": r["name"], "start": r["start"],
                         "end": r.get("end") or (it.end.isoformat()), "location": f"{r['name']}, {r.get('city', '')}"},
        })
        base["links"].append({"label": "Map", "url": maps_url(f"{r['name']} {r.get('city', '')}")})
    return base


def private_item(b: dict) -> dict:
    """Owner-only extras for one booking."""
    out = {k: b[k] for k in ("id", "confirmation", "price", "bookedVia", "provider", "refundable") if k in b}
    if b.get("manageUrl", "").startswith("https://"):
        out["manageUrl"] = b["manageUrl"]
    return out


def apply_actions(alerts: list[dict], actions: dict[str, dict], now: datetime) -> None:
    """A user's Done / Not a problem / Later applies while the alert's
    fingerprint is unchanged (and, for Later, until its date)."""
    for a in alerts:
        act = actions.get(a["id"])
        if not act or act.get("fingerprint") != a["fingerprint"]:
            continue
        st = act.get("status")
        if st == "snoozed":
            try:
                until = parse_dt(act.get("until", ""))
            except ValueError:
                continue
            if until > now:
                a["resolution"] = "snoozed"; a["until"] = act["until"]
        elif st in ("done", "ignored"):
            a["resolution"] = st


def match_trips(computed: list[tuple[Trip, set[str]]], index: list[dict]) -> dict[int, dict]:
    """Keep each trip on its own page across syncs: match by shared bookings."""
    pairs = []
    for ci, (_, ids) in enumerate(computed):
        for ei, e in enumerate(index):
            overlap = len(ids & set(e.get("bookingIds", [])))
            if overlap:
                pairs.append((overlap, ci, ei))
    pairs.sort(reverse=True)
    used_c, used_e, result = set(), set(), {}
    for _, ci, ei in pairs:
        if ci in used_c or ei in used_e:
            continue
        used_c.add(ci); used_e.add(ei); result[ci] = index[ei]
    return result


def build(bookings: list[dict], profile: dict, fares_list: list[dict], now: datetime,
          index: list[dict] | None = None, actions: dict[str, dict[str, dict]] | None = None,
          agent: dict | None = None, sample: bool = False, status_list: list[dict] | None = None,
          chats: dict[str, dict] | None = None, weather: dict | None = None) -> dict:
    prof = {**DEFAULT_PROFILE, **{k: v for k, v in (profile or {}).items() if v not in (None, "")}}
    prof["homeAirports"] = [a.upper() for a in prof.get("homeAirports") or []]
    fares = {f["bookingId"]: f for f in fares_list or []}
    index = [dict(e) for e in (index or [])]
    actions = actions or {}
    by_raw = {b["id"]: b for b in bookings}
    active = [b for b in bookings if b.get("status", "confirmed") != "cancelled"]
    items = [to_item(b) for b in active]
    apply_status(items, {r["bookingId"]: r for r in status_list or [] if r.get("bookingId")}, now, prof)
    chats = chats or {}
    wx = {(d["city"], d["date"]): d for d in (weather or {}).get("days") or [] if d.get("city") and d.get("date")}
    weather_plan: list[dict] = []
    groups = [t for t in group_trips(items, prof) if t.end >= now - timedelta(days=3)]
    computed = [(t, {i.id for i in t.items}) for t in groups]
    matched = match_trips(computed, index)
    taken = {e["slug"] for e in index}
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    trips_out: list[dict] = []
    for ci, (trip, ids) in enumerate(computed):
        city = trip_city(trip, prof)
        start_d = min(i.start_date for i in trip.items)
        end_d = max(i.end_date for i in trip.items)
        cities = trip_cities(trip, prof)
        title = " & ".join(cities[:2]) if cities else city
        entry = matched.get(ci)
        if entry:
            slug, page_title, url = entry["slug"], entry.get("pageTitle") or title, entry.get("url")
        else:
            base = slugify(f"{city}-{start_d.strftime('%Y-%m')}")
            slug, n = base, 2
            while slug in taken:
                slug = f"{base}-{n}"; n += 1
            page_title, url = f"{title}, {MONTHS[start_d.month - 1]} {start_d.year}", None
        taken.add(slug)
        by_id = {i.id: i for i in trip.items}
        travellers = max([int(i.raw.get("travelers") or 1) for i in trip.items] + [1])
        gaps = lodging_gaps(trip, prof)
        nights = trip_nights(trip, prof)
        cities_by_day = day_cities(trip, prof, nights)
        days_wx = []
        for d, c in cities_by_day:
            w = wx.get((c, d))
            if w:
                days_wx.append({"date": d, "city": c, "hi": w.get("hi"), "lo": w.get("lo"), "code": w.get("code"),
                                "rain": w.get("rain"), "kind": w.get("kind", "forecast")})
        if end_d >= now.date():
            per_city: dict[str, list[str]] = {}
            for d, c in cities_by_day:
                per_city.setdefault(c, []).append(d)
            weather_plan += [{"city": c, "dates": ds, "slug": None} for c, ds in per_city.items()]
        alerts = find_alerts(trip, prof, fares)
        for g in gaps:
            a = alert("medium", "lodging_gap", g["label"], "Nothing in your bookings covers these nights.", [])
            a["key"] = g["firstNight"] + "|" + g["city"]; a["gap"] = g
            alerts.append(a)
        for a in alerts:
            enrich_alert(a, by_id, travellers)
        apply_actions(alerts, actions.get(slug, {}), now)
        order = {"high": 0, "medium": 1, "info": 2}
        alerts.sort(key=lambda a: (a.get("resolution") is not None, order[a["level"]]))
        ordered = sorted(trip.items, key=lambda i: display_key(i, trip.items))
        pub_items = [public_item(i) for i in ordered]
        for p, i in zip(pub_items, ordered):
            p["sortKey"] = display_key(i, trip.items).isoformat()
        nxt = next((p for p, i in zip(pub_items, ordered) if i.end >= now), None)
        open_alerts = [a for a in alerts if not a.get("resolution")]
        status = "ongoing" if start_d <= now.date() <= end_d else ("past" if end_d < now.date() else "upcoming")
        counts = {
            "high": sum(a["level"] == "high" for a in open_alerts),
            "medium": sum(a["level"] == "medium" for a in open_alerts),
            "info": sum(a["level"] == "info" for a in open_alerts),
            "handled": len(alerts) - len(open_alerts),
            "gapNights": sum(g["nights"] for g in gaps),
        }
        public = {
            "slug": slug, "title": title, "pageTitle": page_title, "city": city,
            "startDate": start_d.isoformat(), "endDate": end_d.isoformat(), "dates": range_label(start_d, end_d),
            "travellers": travellers, "daysUntil": (start_d - now.date()).days, "status": status,
            "items": pub_items, "gaps": gaps, "alerts": alerts, "nights": nights, "route": trip_route(trip, prof, nights),
            "days": [{"date": d, "city": c} for d, c in cities_by_day], "dayRoutes": day_routes(trip, prof),
            "weather": {"days": days_wx, "checkedAt": (weather or {}).get("checkedAt"), "source": (weather or {}).get("source")} if days_wx else None,
            "next": {"title": nxt["title"], "when": nxt["when"]} if nxt else None,
            "counts": counts, "updatedAt": stamp, "engineVersion": ENGINE_VERSION,
        }
        if sample:
            public["sample"] = True
        private = {
            "items": {i.id: private_item(by_raw[i.id]) for i in trip.items},
            "agent": agent or None, "chat": chats.get(slug) or None, "updatedAt": stamp,
        }
        index_entry = {
            "slug": slug, "url": url, "pageTitle": page_title, "title": title, "dates": public["dates"],
            "startDate": public["startDate"], "endDate": public["endDate"], "status": status,
            "counts": counts, "next": public["next"], "bookingIds": sorted(ids), "sample": sample or None,
            "route": [{"city": s["city"], "mode": s.get("mode"), "kind": s["kind"]} for s in public["route"]],
            "weather": first_per_city(days_wx, now.date().isoformat()),
            "types": {k: sum(1 for i in trip.items if i.type == k) for k in ("flight", "train", "transfer", "hotel", "dining", "other")
                      if any(i.type == k for i in trip.items)},
        }
        trips_out.append({"slug": slug, "isNew": entry is None, "url": url, "public": public,
                          "private": private, "index": index_entry})
    trips_out.sort(key=lambda t: t["public"]["startDate"])
    # Trips on the home index that no longer match anything
    live = {t["slug"] for t in trips_out}
    leftovers = []
    for e in index:
        if e["slug"] in live:
            continue
        e = dict(e)
        if e.get("sample") and not sample:
            e["status"] = "sample"          # sample page, no longer updated
        elif e.get("endDate", "9999") < (now - timedelta(days=3)).date().isoformat():
            e["status"] = "past"
        else:
            e["status"] = "cancelled"
        leftovers.append(e)
    cutoff = now - timedelta(days=30)
    kept = [b for b in bookings if to_item(b).end >= cutoff]
    merged: dict[str, set] = {}
    for e in weather_plan:
        merged.setdefault(e["city"], set()).update(e["dates"])
    return {"trips": trips_out, "leftovers": leftovers, "privateBookings": kept, "updatedAt": stamp,
            "weatherPlan": [{"city": c, "dates": sorted(ds)} for c, ds in sorted(merged.items())],
            "profile": prof, "sample": sample}


# ----------------------------------------------------------------- merge

def merge_key(b: dict) -> tuple:
    """Second identity for a booking, so a schedule-change email updates the
    original booking even if its date (and so its id) moved."""
    code = b.get("confirmation")
    if not code:
        return ("id", b.get("id"))
    t = b.get("type")
    if t == "flight":
        return (t, code, b.get("carrier"), str(b.get("flightNumber", "")).lstrip("0"))
    if t in ("train", "transfer"):
        return (t, code, norm(b.get("fromCity") or b.get("from")), norm(b.get("toCity") or b.get("to")))
    return (t, code)


def merge(existing: list[dict], new: list[dict]) -> tuple[list[dict], list[str]]:
    """New bookings win. A transport booking whose times moved becomes
    status 'changed' with the old times kept in 'previous'."""
    out = list(existing)
    notes: list[str] = []
    index = {merge_key(b): i for i, b in enumerate(out)}
    ids = {b["id"]: i for i, b in enumerate(out)}
    for b in new:
        b = dict(b)
        i = ids.get(b["id"], index.get(merge_key(b)))
        if i is None:
            out.append(b); notes.append(f"added {b['id']}")
            ids[b["id"]] = index[merge_key(b)] = len(out) - 1
            continue
        old = out[i]
        if b.get("type") in TRANSPORT and old.get("depart") and b.get("depart") and b.get("status") != "cancelled":
            moved = parse_dt(old["depart"]) != parse_dt(b["depart"]) or parse_dt(old["arrive"]) != parse_dt(b["arrive"])
            if moved:
                b["status"] = "changed"
                b.setdefault("previous", old.get("previous") or {"depart": old["depart"], "arrive": old["arrive"]})
                notes.append(f"schedule change {b['id']}")
            elif old.get("status") == "changed" and b.get("status", "confirmed") == "confirmed":
                b["status"] = "changed"; b.setdefault("previous", old.get("previous"))
        for k, v in old.items():  # keep facts the new email did not repeat (price, codes)
            b.setdefault(k, v)
        out[i] = b
        notes.append(f"updated {b['id']}" if b.get("status") != "cancelled" else f"cancelled {b['id']}")
    return out, notes



# ----------------------------------------------------------------- batches

TRIP_CAPABILITIES = {
    "db": {"rules": [
        {"path": "", "read": "view", "write": "owner"},
        {"path": "private", "read": "owner", "write": "owner"},
        {"path": "requests", "read": "owner", "write": "owner"},
        {"path": "actions", "read": "view", "write": "admin"},
        {"path": "todos", "read": "view", "write": "interact"},
        {"path": "data/users/{self}", "write": "interact"},
    ]},
    "user": {},
    "mcp": {"servers": [
        {"server": "Google Calendar", "tools": ["create_event"]},
        {"server": "Claude Code Remote", "tools": ["fire_trigger"]},
    ]},
}
HOME_CAPABILITIES = {
    "db": {"rules": [{"path": "", "read": "owner", "write": "owner"}]},
    "user": {},
    "mcp": {"servers": [{"server": "Claude Code Remote", "tools": ["fire_trigger"]}]},
}


class Batch:
    def __init__(self, docs_dir: Path, versions: dict[str, int]):
        self.docs_dir, self.versions, self.writes = docs_dir, versions, []

    def add(self, op: str, collection: str, doc_id: str, data: dict | None = None) -> None:
        key = f"{collection}/{doc_id}"
        e: dict[str, Any] = {"op": op, "collection": collection, "doc_id": doc_id}
        if data is not None:
            self.docs_dir.mkdir(parents=True, exist_ok=True)
            f = self.docs_dir / f"{collection}__{doc_id}.json"
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            e["file_path"] = str(f.resolve())
        if key in self.versions:
            e["if_version"] = self.versions[key]
        elif op == "delete":
            return
        self.writes.append(e)

    def save(self, path: Path) -> None:
        if len(self.writes) > 50:
            raise SystemExit(f"{len(self.writes)} writes is over the 50-write batch limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.writes, indent=1, ensure_ascii=False), encoding="utf-8")


def page_html(template: str, page_title: str) -> str:
    safe = html.escape(page_title, quote=False)
    return re.sub(r"<title>.*?</title>", f"<title>{safe}</title>", template, count=1, flags=re.S)


def write_outputs(result: dict, out: Path, versions: dict, template_path: Path) -> dict:
    """Write per-trip batches, new page files and the pending home index."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "capabilities-trip.json").write_text(json.dumps(TRIP_CAPABILITIES), encoding="utf-8")
    (out / "capabilities-home.json").write_text(json.dumps(HOME_CAPABILITIES), encoding="utf-8")
    template = template_path.read_text(encoding="utf-8")
    plan: dict[str, Any] = {"newTrips": [], "trips": [], "homeBatch": "run: wayfare.py home-batch"}
    tv = versions.get("trips", {})
    for t in result["trips"]:
        slug = t["slug"]
        b = Batch(out / "trips" / slug / "docs", tv.get(slug, {}))
        b.add("set", "trip", "data", t["public"])
        b.add("set", "private", "data", t["private"])
        batch_path = out / "trips" / slug / "batch.json"
        b.save(batch_path)
        entry = {"slug": slug, "pageTitle": t["public"]["pageTitle"], "url": t["url"], "batch": str(batch_path)}
        if t["isNew"]:
            page = out / "pages" / f"{slug}.html"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(page_html(template, t["public"]["pageTitle"]), encoding="utf-8")
            entry["page"] = str(page)
            plan["newTrips"].append(entry)
        plan["trips"].append(entry)
    for e in result["leftovers"]:
        if e["status"] == "cancelled" and e.get("url"):
            b = Batch(out / "trips" / e["slug"] / "docs", tv.get(e["slug"], {}))
            if "trip/data" in tv.get(e["slug"], {}):
                b.add("update", "trip", "data", {"status": "cancelled", "updatedAt": result["updatedAt"]})
                batch_path = out / "trips" / e["slug"] / "batch.json"
                b.save(batch_path)
                plan["trips"].append({"slug": e["slug"], "url": e["url"], "batch": str(batch_path), "cancelled": True})
    pending = {
        "index": [t["index"] for t in result["trips"]] + result["leftovers"],
        "privateBookings": None if result["sample"] else result["privateBookings"],
        "updatedAt": result["updatedAt"],
        "versions": versions.get("home", {}),
    }
    (out / "home-pending.json").write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    return plan


def home_batch(out: Path, urls: dict[str, str]) -> Path:
    pending = json.loads((out / "home-pending.json").read_text(encoding="utf-8"))
    index = pending["index"]
    missing = []
    for e in index:
        if not e.get("url"):
            e["url"] = urls.get(e["slug"])
            if not e["url"]:
                missing.append(e["slug"])
    if missing:
        raise SystemExit(f"No page url for: {', '.join(missing)}. Publish those pages first and add them to --urls.")
    b = Batch(out / "home" / "docs", pending["versions"])
    b.add("set", "index", "trips", {"trips": index, "updatedAt": pending["updatedAt"], "engineVersion": ENGINE_VERSION})
    if pending["privateBookings"] is not None:
        b.add("set", "private", "bookings", {"bookings": pending["privateBookings"], "updatedAt": pending["updatedAt"]})
    path = out / "home" / "batch.json"
    b.save(path)
    return path


# ----------------------------------------------------------------- CLI

def load_json(path: str | Path | None, default: Any) -> Any:
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    text = p.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else default


def unwrap(data: Any) -> Any:
    """Accept a saved db document either bare or as {data: {...}}."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and len(data) <= 3:
        return data["data"]
    return data


def load_bookings(path: str) -> list[dict]:
    data = unwrap(load_json(path, []))
    if isinstance(data, dict) and "bookings" in data:
        data = data["bookings"]
    return data


def load_actions(db_dir: str | None) -> dict[str, dict[str, dict]]:
    """Read wayfare-work/db/trips/<slug>/actions/<alertId>.json files."""
    out: dict[str, dict[str, dict]] = {}
    if not db_dir:
        return out
    root = Path(db_dir)
    for f in root.glob("*/actions/*.json"):
        slug = f.parent.parent.name
        try:
            d = unwrap(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            out.setdefault(slug, {})[d.get("alertId") or f.stem] = d
    return out


def get_now(arg: str | None) -> datetime:
    return parse_dt(arg) if arg else datetime.now(timezone.utc)


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def cmd_validate(a: argparse.Namespace) -> int:
    errs = validate(load_bookings(a.bookings))
    if errs:
        print("\n".join(errs))
        return 1
    print("OK: bookings are valid")
    return 0


def run_build(a: argparse.Namespace) -> dict:
    bookings = load_bookings(a.bookings)
    errs = validate(bookings)
    if errs:
        raise SystemExit("Bookings are not valid. Fix these first:\n" + "\n".join(errs))
    profile = unwrap(load_json(a.profile, {}))
    fares = unwrap(load_json(a.fares, []))
    if isinstance(fares, dict):
        fares = fares.get("results", [])
    index = unwrap(load_json(getattr(a, "index", None), {}))
    if isinstance(index, dict):
        index = index.get("trips", [])
    agent = unwrap(load_json(getattr(a, "agent", None), None))
    status = unwrap(load_json(getattr(a, "status", None), []))
    if isinstance(status, dict):
        status = status.get("results", [])
    weather = unwrap(load_json(getattr(a, "weather", None), {}))
    chats = unwrap(load_json(getattr(a, "chats", None), {}))
    if isinstance(chats, dict) and isinstance(chats.get("chats"), dict):
        chats = chats["chats"]
    return build(bookings, profile, fares, get_now(a.now), index=index,
                 actions=load_actions(getattr(a, "trips_db", None)), agent=agent,
                 sample=getattr(a, "sample", False), status_list=status, chats=chats, weather=weather)


def cmd_build(a: argparse.Namespace) -> int:
    result = run_build(a)
    out = Path(a.out_dir)
    versions = load_json(a.versions, {})
    plan = write_outputs(result, out, versions, Path(a.template or plugin_root() / "dashboard" / "trip.html"))
    summary = {
        "trips": [{"slug": t["slug"], "page": t["public"]["pageTitle"], "new": t["isNew"],
                   "open": [f"[{x['level']}] {x['title']}" for x in t["public"]["alerts"] if not x.get("resolution")],
                   "handled": t["public"]["counts"]["handled"]} for t in result["trips"]],
        "noLongerMatched": [{"slug": e["slug"], "status": e["status"]} for e in result["leftovers"]],
        "newPages": [n["page"] for n in plan["newTrips"]],
        "plan": str(out / "plan.json"),
    }
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    return 0


def cmd_home_batch(a: argparse.Namespace) -> int:
    path = home_batch(Path(a.out_dir), load_json(a.urls, {}))
    print(f"Wrote {path}")
    return 0


def cmd_capabilities(a: argparse.Namespace) -> int:
    print(json.dumps(TRIP_CAPABILITIES if a.page == "trip" else HOME_CAPABILITIES))
    return 0


def cmd_link(a: argparse.Namespace) -> int:
    if a.kind == "stays":
        print(stays_search_url(a.query, a.check_in, a.check_out, a.guests))
    else:
        print(maps_url(a.query))
    return 0


def cmd_merge(a: argparse.Namespace) -> int:
    existing = load_bookings(a.existing) if a.existing else []
    new = load_bookings(a.new)
    errs = validate(new)
    if errs:
        print("New bookings are not valid. Fix these first:\n" + "\n".join(errs), file=sys.stderr)
        return 1
    merged, notes = merge(existing, new)
    errs = validate(merged)
    if errs:
        print("Merged bookings are not valid:\n" + "\n".join(errs), file=sys.stderr)
        return 1
    Path(a.out).write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"total": len(merged), "changes": notes, "out": a.out}, indent=1))
    return 0


STATIC_SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                   '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                   '<style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style>'
                   '</head><body>%s</body></html>')


def cmd_render_static(a: argparse.Namespace) -> int:
    """One standalone HTML file per trip, for Claude Code in a terminal or for testing."""
    result = run_build(a)
    template = Path(a.template or plugin_root() / "dashboard" / "trip.html").read_text(encoding="utf-8")
    marker = "<!--WAYFARE_STATIC_DATA-->"
    if marker not in template:
        print(f"template has no {marker} marker", file=sys.stderr)
        return 1
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    written = []
    for t in result["trips"]:
        payload = {"trip": t["public"]}
        if a.owner:
            payload["private"] = {"items": t["private"]["items"]}
        blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
        body = page_html(template, t["public"]["pageTitle"]).replace(
            marker, f'<script id="wayfare-static" type="application/json">{blob}</script>', 1)
        f = out / f"{t['slug']}.html"
        f.write_text(STATIC_SKELETON % body, encoding="utf-8")
        written.append(str(f))
    print(json.dumps({"written": written}, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wayfare", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--bookings", required=True); v.set_defaults(fn=cmd_validate)

    def build_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--bookings", required=True)
        sp.add_argument("--profile"); sp.add_argument("--fares", help="fare_check.py output or private/fares doc")
        sp.add_argument("--index", help="home index/trips doc (trip slugs, page urls, booking ids)")
        sp.add_argument("--trips-db", help="folder with <slug>/actions/*.json saved from each trip page")
        sp.add_argument("--agent", help="home private/agent doc ({triggerId})")
        sp.add_argument("--status", help="flight_status.py output or home private/status doc")
        sp.add_argument("--chats", help='home private/chats doc: {"chats": {"<slug>": {"triggerId", "url"}}}')
        sp.add_argument("--weather", help="weather.py output or home private/weather doc")
        sp.add_argument("--sample", action="store_true", help="mark pages as sample data; never write private/bookings")
        sp.add_argument("--template", help="trip page template (default dashboard/trip.html)")
        sp.add_argument("--now", help="override current time (ISO with offset), for tests")

    wp = sub.add_parser("weather-plan", help="print the cities and dates that weather.py should fetch")
    build_args(wp)
    wp.set_defaults(fn=lambda a: print(json.dumps(run_build(a)["weatherPlan"], indent=1)) or 0)

    b = sub.add_parser("build", help="build per-trip batches, new page files and the pending home index")
    build_args(b)
    b.add_argument("--versions", help='{"home": {"index/trips": n, ...}, "trips": {"<slug>": {"trip/data": n, ...}}}')
    b.add_argument("--out-dir", required=True)
    b.set_defaults(fn=cmd_build)
    h = sub.add_parser("home-batch", help="after new pages are published: write the home batch with their urls")
    h.add_argument("--out-dir", required=True); h.add_argument("--urls", help='{"<slug>": "<artifact url>"}')
    h.set_defaults(fn=cmd_home_batch)
    c = sub.add_parser("capabilities"); c.add_argument("--page", choices=["trip", "home"], required=True)
    c.set_defaults(fn=cmd_capabilities)
    lk = sub.add_parser("link", help="print a stays-search or map link")
    lk.add_argument("kind", choices=["stays", "map"]); lk.add_argument("--query", required=True, help="city or hotel name")
    lk.add_argument("--check-in"); lk.add_argument("--check-out"); lk.add_argument("--guests", type=int, default=2)
    lk.set_defaults(fn=cmd_link)
    m = sub.add_parser("merge", help="merge newly extracted bookings into the stored list")
    m.add_argument("--existing"); m.add_argument("--new", required=True); m.add_argument("--out", required=True)
    m.set_defaults(fn=cmd_merge)
    r = sub.add_parser("render-static", help="standalone HTML per trip")
    build_args(r)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--owner", action="store_true", help="include full codes and prices (do not share the files)")
    r.set_defaults(fn=cmd_render_static)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
