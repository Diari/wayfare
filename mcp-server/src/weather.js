// Trip weather from Open-Meteo (free, no key), same method as
// plugins/wayfare-claude/scripts/weather.py:
//   * a forecast for days in the next 16 days;
//   * for later days, the weather on the same dates last year ("lastYear"),
//     a simple guide for packing, not a forecast.

import { addDays, dayNum, isDate } from "./itinerary.js";

const GEO = "https://geocoding-api.open-meteo.com/v1/search";
const FORECAST = "https://api.open-meteo.com/v1/forecast";
const ARCHIVE = "https://archive-api.open-meteo.com/v1/archive";
export const FORECAST_DAYS = 16;
export const MAX_DAYS = 31;

const CODES = {
  0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "fog", 48: "fog",
  51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
  61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
  71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
  80: "rain showers", 81: "rain showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers",
  95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
};
export const describe = (code) => CODES[code] || "mixed";
export const isSnow = (code) => [71, 73, 75, 77, 85, 86].includes(code);

export function shiftYear(d, years = -1) {
  const [y, m, day] = d.split("-");
  const out = `${Number(y) + years}-${m}-${day}`;
  return isDate(out) && new Date(out + "T00:00:00Z").getUTCDate() === Number(day) ? out : `${Number(y) + years}-${m}-28`;
}

async function getJson(fetcher, url, params) {
  let r;
  try {
    r = await fetcher(`${url}?${new URLSearchParams(params)}`, {
      headers: { Accept: "application/json", "User-Agent": "wayfare-mcp (+https://github.com/Diari/wayfare)" },
    });
  } catch {
    throw new Error("cannot reach Open-Meteo right now; try again later");
  }
  if (!r.ok) throw new Error(`Open-Meteo returned HTTP ${r.status}; try again later`);
  try { return await r.json(); } catch { throw new Error("Open-Meteo sent an answer that is not JSON; try again later"); }
}

function rows(resp, kind) {
  const d = (resp && resp.daily) || {};
  const rainKey = kind === "forecast" ? "precipitation_probability_max" : "precipitation_sum";
  const out = {};
  (d.time || []).forEach((day, i) => {
    const hi = (d.temperature_2m_max || [])[i], lo = (d.temperature_2m_min || [])[i];
    if (hi == null || lo == null) return;
    const code = (d.weather_code || [])[i];
    const rain = (d[rainKey] || [])[i];
    out[day] = {
      hi: Math.round(hi), lo: Math.round(lo), code, sky: describe(code), kind,
      ...(kind === "forecast" ? { rainChance: rain ?? null } : { rainMm: rain ?? null }),
    };
  });
  return out;
}

export function checkDates(start, end, today) {
  if (!isDate(start) || !isDate(end)) return "start_date and end_date must be YYYY-MM-DD";
  if (end < start) return "end_date is before start_date";
  if (dayNum(end) - dayNum(start) + 1 > MAX_DAYS) return `at most ${MAX_DAYS} days in one request`;
  if (end < today) return "these dates are in the past";
  return null;
}

export async function tripWeather({ city, start_date, end_date }, { fetcher = fetch, today } = {}) {
  today = today || new Date().toISOString().slice(0, 10);
  const name = String(city || "").trim().slice(0, 100);
  if (!name) return { ok: false, error: "city is required" };
  const bad = checkDates(start_date, end_date, today);
  if (bad) return { ok: false, error: bad };

  const geo = await getJson(fetcher, GEO, { name, count: 1, language: "en", format: "json" });
  const hit = (geo.results || [])[0];
  if (!hit) return { ok: false, error: `no place found for '${name}'` };
  const place = { name: hit.name, country: hit.country || null, lat: hit.latitude, lon: hit.longitude, timezone: hit.timezone || null };

  const dates = [];
  for (let d = start_date < today ? today : start_date; d <= end_date; d = addDays(d, 1)) dates.push(d);
  const limit = addDays(today, FORECAST_DAYS);
  const near = dates.filter((d) => d < limit), far = dates.filter((d) => d >= limit);
  const common = { latitude: place.lat, longitude: place.lon, timezone: "auto" };
  const byDate = {};
  if (near.length) {
    Object.assign(byDate, rows(await getJson(fetcher, FORECAST, {
      ...common, daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
      start_date: near[0], end_date: near.at(-1),
    }), "forecast"));
  }
  if (far.length) {
    const last = rows(await getJson(fetcher, ARCHIVE, {
      ...common, daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
      start_date: shiftYear(far[0]), end_date: shiftYear(far.at(-1)),
    }), "lastYear");
    for (const d of far) if (last[shiftYear(d)]) byDate[d] = last[shiftYear(d)];
  }
  const days = dates.filter((d) => byDate[d]).map((d) => ({ date: d, ...byDate[d] }));
  return {
    ok: true, place, days,
    summary: summarize(days),
    note: far.length ? "Days after the next 16 show the weather on the same dates last year, as a packing guide, not a forecast." : undefined,
    source: "Open-Meteo (open-meteo.com), CC BY 4.0",
  };
}

export function summarize(days) {
  if (!days.length) return null;
  const hi = Math.max(...days.map((d) => d.hi)), lo = Math.min(...days.map((d) => d.lo));
  const wet = days.filter((d) => (d.rainChance ?? 0) >= 40 || (d.rainMm ?? 0) >= 1).length;
  const snow = days.some((d) => isSnow(d.code));
  return { hi, lo, wetDays: wet, snow, days: days.length };
}
