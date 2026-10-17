#!/usr/bin/env python3
"""Wayfare weather (optional, free, no key).

Gets the weather for each day and city of your trips from Open-Meteo
(https://open-meteo.com):
  * a forecast for days in the next 16 days;
  * for later days, the weather on the same dates last year, shown on the
    page as "last year" (a simple guide for packing, not a forecast).

Input: the plan printed by `wayfare.py weather-plan` ([{city, dates}]).
Output: {"days": [{city, date, hi, lo, code, rain, kind}], "places": {...},
"checkedAt"} for `wayfare.py build --weather`.

In a cloud session the environment must allow these hosts (Network access:
Custom): api.open-meteo.com, geocoding-api.open-meteo.com,
archive-api.open-meteo.com. Open-Meteo is free for non-commercial use.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_DAYS = 16


def get(url: str, params: dict, timeout: float = 30.0) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"Accept": "application/json", "User-Agent": "wayfare-plugin"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def geocode(city: str) -> dict | None:
    r = get(GEO, {"name": city, "count": 1, "language": "en", "format": "json"})
    hits = r.get("results") or []
    if not hits:
        return None
    h = hits[0]
    return {"lat": h["latitude"], "lon": h["longitude"], "country": h.get("country"), "timezone": h.get("timezone")}


def daily_rows(resp: dict, kind: str) -> dict[str, dict]:
    d = resp.get("daily") or {}
    out = {}
    rain_key = "precipitation_probability_max" if kind == "forecast" else "precipitation_sum"
    for i, day in enumerate(d.get("time") or []):
        def at(key):
            vals = d.get(key) or []
            return vals[i] if i < len(vals) else None
        hi, lo = at("temperature_2m_max"), at("temperature_2m_min")
        if hi is None or lo is None:
            continue
        out[day] = {"hi": round(hi), "lo": round(lo), "code": at("weather_code"), "rain": at(rain_key), "kind": kind}
    return out


def split_dates(dates: list[str], today: date) -> tuple[list[str], list[str]]:
    near, far = [], []
    for s in dates:
        d = date.fromisoformat(s)
        if d < today:
            continue
        (near if d < today + timedelta(days=FORECAST_DAYS) else far).append(s)
    return near, far


def shift_year(s: str, years: int = -1) -> str:
    d = date.fromisoformat(s)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:            # 29 February
        return d.replace(year=d.year + years, day=28).isoformat()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--plan", required=True, help="output of wayfare.py weather-plan")
    p.add_argument("--previous", help="earlier weather output (place cache)")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    prev = {}
    if a.previous and Path(a.previous).exists() and Path(a.previous).read_text().strip():
        prev = json.loads(Path(a.previous).read_text(encoding="utf-8"))
        prev = prev.get("data", prev) if isinstance(prev, dict) and "days" not in prev else prev
    places = dict((prev or {}).get("places") or {})
    now = datetime.now(timezone.utc)
    today = now.date()
    days: list[dict] = []
    report = {"cities": 0, "requests": 0, "error": None}
    try:
        for entry in plan:
            city = entry["city"]
            if city not in places:
                g = geocode(city); report["requests"] += 1
                if not g:
                    continue
                places[city] = g
            pl = places[city]
            near, far = split_dates(sorted(set(entry["dates"])), today)
            rows: dict[str, dict] = {}
            if near:
                rows.update(daily_rows(get(FORECAST, {
                    "latitude": pl["lat"], "longitude": pl["lon"], "timezone": "auto",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "start_date": near[0], "end_date": near[-1]}), "forecast"))
                report["requests"] += 1
            if far:
                last = daily_rows(get(ARCHIVE, {
                    "latitude": pl["lat"], "longitude": pl["lon"], "timezone": "auto",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "start_date": shift_year(far[0]), "end_date": shift_year(far[-1])}), "lastYear")
                report["requests"] += 1
                for s in far:
                    r = last.get(shift_year(s))
                    if r:
                        rows[s] = r
            for s in sorted(rows):
                if s in entry["dates"]:
                    days.append({"city": city, "date": s, **rows[s]})
            report["cities"] += 1
    except urllib.error.HTTPError as e:
        report["error"] = f"Open-Meteo returned HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        report["error"] = (f"Cannot reach Open-Meteo ({e}). In a cloud session, allow api.open-meteo.com, "
                           "geocoding-api.open-meteo.com and archive-api.open-meteo.com.")
    out = {"days": days, "places": places, "checkedAt": now.isoformat(timespec="seconds"), "source": "Open-Meteo"}
    if report["error"] and not days and prev.get("days"):
        out = prev                                   # keep the last good data
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
