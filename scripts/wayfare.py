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
  build          Build dashboard documents and an ArtifactData batch file.
  render-static  Write a standalone HTML dashboard (for Claude Code in a
                 terminal, or for local testing).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ENGINE_VERSION = "0.1.0"
TRANSPORT = {"flight", "train", "transfer"}
TYPES = TRANSPORT | {"hotel", "dining", "other"}
STATUSES = {"confirmed", "changed", "cancelled"}
DEFAULT_PROFILE = {
    "homeAirports": [],
    "homeCity": "",
    "minConnectionMinutes": 75,
    "arrivalToDinnerMinutes": 150,
    "fareDropMinimum": 25,
}
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


def alert(level: str, kind: str, title: str, detail: str, item_ids: list[str]) -> dict:
    return {"level": level, "kind": kind, "title": title, "detail": detail, "itemIds": item_ids}


def find_alerts(trip: Trip, prof: dict, fares: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    items = sorted(trip.items, key=lambda i: i.start)
    transport = [i for i in items if i.type in TRANSPORT]
    changed_ids = {i.id for i in items if i.status == "changed"}

    # 1. schedule changes
    for it in items:
        if it.status == "changed" and it.raw.get("previous"):
            p = it.raw["previous"]
            parts = []
            if p.get("depart"):
                parts.append(f"departs {parse_dt(p['depart']).strftime('%H:%M')} → {it.start.strftime('%H:%M')}")
            if p.get("arrive"):
                parts.append(f"arrives {parse_dt(p['arrive']).strftime('%H:%M')} → {it.end.strftime('%H:%M')}")
            out.append(alert("high", "schedule_change", f"Schedule changed: {title_of(it)}",
                             "; ".join(parts) + ". Check what this affects below.", [it.id]))

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
    """Shared-safe view of a booking: no prices, no full codes, no notes."""
    r = it.raw
    base = {"id": it.id, "type": it.type, "status": it.status, "code": mask_code(r.get("confirmation")),
            "day": it.start_date.isoformat(), "dayLabel": day_label(it.start_date),
            "time": it.start.strftime("%H:%M") if it.type != "hotel" else (r.get("checkInFrom") or "Check-in"),
            "endTime": it.end.strftime("%H:%M") if it.type in TRANSPORT else None,
            "endDayOffset": (it.end_date - it.start_date).days if it.type in TRANSPORT else 0}
    if it.type in TRANSPORT:
        route = f"{r.get('from', '')} → {r.get('to', '')}" if it.type == "flight" else f"{it.city_from} → {it.city_to}"
        sub = [s for s in [r.get("provider"), f"{r.get('carrier', '')} {r.get('flightNumber', '')}".strip() if it.type == "flight" else r.get("name"),
                           r.get("cabin"), f"{r['travelers']} travellers" if r.get("travelers", 1) > 1 else None] if s]
        base.update({
            "title": f"{it.city_from} → {it.city_to}" if it.type == "flight" else route,
            "route": route,
            "subtitle": " · ".join(sub),
            "when": time_label(it.start),
            "until": time_label(it.end) if it.end_date != it.start_date else it.end.strftime("%H:%M"),
            "sortKey": it.start.astimezone(timezone.utc).isoformat(),
        })
        if it.status == "changed" and r.get("previous"):
            p = r["previous"]
            base["previous"] = {k: time_label(parse_dt(v)) for k, v in p.items() if k in ("depart", "arrive")}
    elif it.type == "hotel":
        n = (it.end_date - it.start_date).days
        base.update({
            "title": r["name"],
            "subtitle": " · ".join(s for s in [r["city"], r.get("provider"), f"{r['travelers']} guests" if r.get("travelers", 1) > 1 else None] if s),
            "when": f"{day_label(it.start_date)} → {day_label(it.end_date)}",
            "until": f"{n} night{'s' if n != 1 else ''}",
            "sortKey": it.start.isoformat(),
        })
    else:
        base.update({
            "title": r["name"],
            "subtitle": " · ".join(s for s in [r.get("city"), r.get("provider"), f"Table for {r['partySize']}" if r.get("partySize") else None] if s),
            "when": time_label(it.start),
            "until": "",
            "sortKey": it.start.astimezone(timezone.utc).isoformat(),
        })
    return base


def build(bookings: list[dict], profile: dict, fares_list: list[dict], now: datetime) -> dict:
    prof = {**DEFAULT_PROFILE, **{k: v for k, v in (profile or {}).items() if v not in (None, "")}}
    prof["homeAirports"] = [a.upper() for a in prof.get("homeAirports") or []]
    fares = {f["bookingId"]: f for f in fares_list or []}
    active = [b for b in bookings if b.get("status", "confirmed") != "cancelled"]
    items = [to_item(b) for b in active]
    trips_out = []
    used_slugs: set[str] = set()
    for trip in group_trips(items, prof):
        if trip.end < now - timedelta(days=3):
            continue  # finished trips leave the dashboard
        city = trip_city(trip, prof)
        start_d = min(i.start_date for i in trip.items)
        end_d = max(i.end_date for i in trip.items)
        slug = slugify(f"{city}-{start_d.strftime('%Y-%m')}")
        base = slug; n = 2
        while slug in used_slugs:
            slug = f"{base}-{n}"; n += 1
        used_slugs.add(slug)
        gaps = lodging_gaps(trip, prof)
        alerts = find_alerts(trip, prof, fares)
        for g in gaps:
            alerts.append(alert("medium", "lodging_gap", g["label"], "Nothing in your bookings covers these nights.", []))
        order = {"high": 0, "medium": 1, "info": 2}
        alerts.sort(key=lambda a: order[a["level"]])
        travellers = max([int(i.raw.get("travelers") or 1) for i in trip.items] + [1])
        cities = trip_cities(trip, prof)
        ordered = sorted(trip.items, key=lambda i: display_key(i, trip.items))
        public_items = [public_item(i) for i in ordered]
        for p, i in zip(public_items, ordered):
            p["sortKey"] = display_key(i, trip.items).isoformat()
        nxt = next((p for p, i in zip(public_items, ordered) if i.end >= now), None)
        trips_out.append({
            "slug": slug,
            "title": " & ".join(cities[:2]) if cities else city,
            "city": city,
            "startDate": start_d.isoformat(),
            "endDate": end_d.isoformat(),
            "dates": range_label(start_d, end_d),
            "travellers": travellers,
            "daysUntil": (start_d - now.date()).days,
            "items": public_items,
            "gaps": gaps,
            "alerts": alerts,
            "next": {"title": nxt["title"], "when": nxt["when"]} if nxt else None,
            "counts": {
                "high": sum(a["level"] == "high" for a in alerts),
                "medium": sum(a["level"] == "medium" for a in alerts),
                "info": sum(a["level"] == "info" for a in alerts),
                "gapNights": sum(g["nights"] for g in gaps),
            },
        })
    trips_out.sort(key=lambda t: t["startDate"])
    status = {
        "engineVersion": ENGINE_VERSION,
        "updatedAt": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "tripSlugs": [t["slug"] for t in trips_out],
        "bookingCount": len(active),
        "alertCount": sum(len(t["alerts"]) for t in trips_out),
        "highCount": sum(t["counts"]["high"] for t in trips_out),
    }
    # keep private bookings bounded: drop anything that ended > 30 days ago
    cutoff = now - timedelta(days=30)
    kept = [b for b in bookings if to_item(b).end >= cutoff] if bookings else []
    return {"trips": trips_out, "status": status, "privateBookings": kept, "profile": prof}


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


def batch_writes(result: dict, profile_raw: dict, existing: dict[str, int], include_profile: bool,
                 docs_dir: Path | None = None, write_bookings: bool = True) -> list[dict]:
    """ArtifactData batch entries. `existing` maps 'collection/doc_id' to the
    version last read; entries for existing docs get if_version, and trips
    that are gone get a delete. With docs_dir, each document is written to a
    file and the entry uses file_path (keeps the tool call small)."""
    writes: list[dict] = []

    def add(op: str, collection: str, doc_id: str, data: dict | None = None) -> None:
        e: dict[str, Any] = {"op": op, "collection": collection, "doc_id": doc_id}
        if data is not None:
            if docs_dir is not None:
                docs_dir.mkdir(parents=True, exist_ok=True)
                f = docs_dir / f"{collection}__{doc_id}.json"
                f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                e["file_path"] = str(f.resolve())
            else:
                e["data"] = data
        key = f"{collection}/{doc_id}"
        if key in existing:
            e["if_version"] = existing[key]
        elif op == "delete":
            return
        writes.append(e)

    for t in result["trips"]:
        add("set", "trips", t["slug"], t)
    for key in existing:
        coll, _, doc = key.rpartition("/")
        if coll == "trips" and doc not in {t["slug"] for t in result["trips"]}:
            add("delete", "trips", doc)
    add("set", "meta", "status", result["status"])
    if write_bookings:  # sample data never goes into the real booking list
        add("set", "private", "bookings", {"bookings": result["privateBookings"],
                                           "updatedAt": result["status"]["updatedAt"]})
    if include_profile:
        add("set", "private", "profile", profile_raw)
    if len(writes) > 50:
        raise SystemExit(f"{len(writes)} writes is over the 50-write batch limit; split the batch")
    return writes


# ----------------------------------------------------------------- CLI

def load_json(path: str | None, default: Any) -> Any:
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    data = json.loads(p.read_text(encoding="utf-8"))
    return data


def load_bookings(path: str) -> list[dict]:
    data = load_json(path, [])
    # accept a bare array, {bookings: [...]}, or a saved db document {data: {bookings: [...]}, ...}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data, dict) and "bookings" in data:
        data = data["bookings"]
    return data


def get_now(arg: str | None) -> datetime:
    return parse_dt(arg) if arg else datetime.now(timezone.utc)


def cmd_validate(a: argparse.Namespace) -> int:
    errs = validate(load_bookings(a.bookings))
    if errs:
        print("\n".join(errs))
        return 1
    print("OK: bookings are valid")
    return 0


def cmd_build(a: argparse.Namespace) -> int:
    bookings = load_bookings(a.bookings)
    errs = validate(bookings)
    if errs:
        print("Bookings are not valid. Fix these first:\n" + "\n".join(errs), file=sys.stderr)
        return 1
    profile_raw = load_json(a.profile, {})
    if isinstance(profile_raw, dict) and "profile" in profile_raw and isinstance(profile_raw["profile"], dict):
        profile_raw = profile_raw["profile"]
    fares = load_json(a.fares, [])
    if isinstance(fares, dict):
        fares = fares.get("results", [])
    result = build(bookings, profile_raw, fares, get_now(a.now))
    if a.sample:
        result["status"]["sample"] = True
    existing = load_json(a.versions, {})
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    writes = batch_writes(result, profile_raw, existing, a.include_profile, docs_dir=out / "docs",
                          write_bookings=not a.sample)
    (out / "batch.json").write_text(json.dumps(writes, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "dashboard-data.json").write_text(json.dumps({"trips": result["trips"], "status": result["status"]},
                                                        indent=1, ensure_ascii=False), encoding="utf-8")
    s = result["status"]
    print(json.dumps({
        "trips": [{"slug": t["slug"], "title": t["title"], "dates": t["dates"],
                   "alerts": [f"[{x['level']}] {x['title']}" for x in t["alerts"]]} for t in result["trips"]],
        "bookings": s["bookingCount"], "writes": len(writes),
        "batchFile": str(out / "batch.json"),
    }, indent=1, ensure_ascii=False))
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


def cmd_render_static(a: argparse.Namespace) -> int:
    bookings = load_bookings(a.bookings)
    errs = validate(bookings)
    if errs:
        print("\n".join(errs), file=sys.stderr)
        return 1
    result = build(bookings, load_json(a.profile, {}), load_json(a.fares, []), get_now(a.now))
    template = Path(a.template or Path(__file__).resolve().parent.parent / "dashboard" / "index.html").read_text(encoding="utf-8")
    payload = {"trips": result["trips"], "status": result["status"]}
    if a.owner:
        payload["privateBookings"] = result["privateBookings"]
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    marker = "<!--WAYFARE_STATIC_DATA-->"
    if marker not in template:
        print(f"template has no {marker} marker", file=sys.stderr)
        return 1
    body = template.replace(marker, f'<script id="wayfare-static" type="application/json">{blob}</script>', 1)
    # The template is an Artifact page (no document skeleton); add one for a standalone file.
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>:root{color-scheme:light}body{margin:0}[hidden]{display:none!important}</style>'
            f'</head><body>{body}</body></html>')
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"Wrote {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="wayfare", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--bookings", required=True); v.set_defaults(fn=cmd_validate)
    b = sub.add_parser("build")
    b.add_argument("--bookings", required=True)
    b.add_argument("--profile")
    b.add_argument("--fares", help="fare_check.py output")
    b.add_argument("--versions", help="JSON map {'trips/<slug>': version, 'meta/status': version, ...} of docs that exist")
    b.add_argument("--include-profile", action="store_true", help="also write private/profile")
    b.add_argument("--sample", action="store_true", help="mark the dashboard as showing sample data")
    b.add_argument("--now", help="override current time (ISO with offset), for tests")
    b.add_argument("--out-dir", required=True)
    b.set_defaults(fn=cmd_build)
    m = sub.add_parser("merge", help="merge newly extracted bookings into the stored list")
    m.add_argument("--existing", help="stored bookings (array or {bookings: [...]}); may be missing")
    m.add_argument("--new", required=True); m.add_argument("--out", required=True)
    m.set_defaults(fn=cmd_merge)
    r = sub.add_parser("render-static")
    r.add_argument("--bookings", required=True); r.add_argument("--profile"); r.add_argument("--fares")
    r.add_argument("--now"); r.add_argument("--template"); r.add_argument("--out", required=True)
    r.add_argument("--owner", action="store_true", help="include full codes and prices (do not share the file)")
    r.set_defaults(fn=cmd_render_static)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
