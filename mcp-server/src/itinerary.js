// Wayfare itinerary check: a JavaScript port of the trip rules in
// plugins/wayfare-claude/scripts/wayfare.py (group_trips, lodging_gaps and
// find_alerts sections 1-5). Pure functions: no network, no storage.
//
// Times are ISO 8601 with a UTC offset ("2026-11-06T07:05:00+01:00"). We keep
// the wall-clock date and time as written (local to the place) and the
// absolute instant for ordering, like Python's aware datetimes.

export const TRANSPORT = new Set(["flight", "train", "transfer"]);
export const TYPES = new Set([...TRANSPORT, "hotel", "dining", "other"]);
export const DEFAULTS = { homeAirports: [], homeCity: "", minConnectionMinutes: 75, arrivalToDinnerMinutes: 150 };
export const MAX_BOOKINGS = 200;

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ISO_DT = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;
const ISO_D = /^\d{4}-\d{2}-\d{2}$/;
const DAY = 86400000;

export function parseDt(s) {
  const m = ISO_DT.exec(String(s || ""));
  if (!m) throw new Error(`time '${s}' must be ISO 8601 with a UTC offset (example: 2026-11-06T07:05:00+01:00)`);
  const ms = Date.parse(s);
  if (Number.isNaN(ms)) throw new Error(`time '${s}' is not a real time`);
  return { ms, date: m[1], hm: `${m[2]}:${m[3]}` };
}

export function isDate(s) {
  return ISO_D.test(String(s || "")) && !Number.isNaN(Date.parse(s + "T00:00:00Z"));
}

export const dayNum = (d) => Math.round(Date.parse(d + "T00:00:00Z") / DAY);
export const fromDayNum = (n) => new Date(n * DAY).toISOString().slice(0, 10);
export const addDays = (d, n) => fromDayNum(dayNum(d) + n);

export function dayLabel(d) {
  const dt = new Date(d + "T00:00:00Z");
  return `${WEEKDAYS[(dt.getUTCDay() + 6) % 7]} ${dt.getUTCDate()} ${MONTHS[dt.getUTCMonth()]}`;
}

function rangeLabel(a, b) {
  const [ya, ma, da] = a.split("-").map(Number);
  const [yb, mb, db] = b.split("-").map(Number);
  if (ya === yb && ma === mb) return `${da}–${db} ${MONTHS[ma - 1]} ${ya}`;
  return `${da} ${MONTHS[ma - 1]} – ${db} ${MONTHS[mb - 1]} ${yb}`;
}

const norm = (t) => String(t || "").trim().toLowerCase();
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

// ---------------------------------------------------------------- validation

export function validate(bookings) {
  if (!Array.isArray(bookings)) return ["bookings must be an array"];
  if (bookings.length > MAX_BOOKINGS) return [`at most ${MAX_BOOKINGS} bookings in one check`];
  const errs = [];
  const seen = new Set();
  bookings.forEach((b, i) => {
    const where = `bookings[${i}] (${b && b.id ? b.id : "?"})`;
    if (!b || typeof b !== "object") { errs.push(`bookings[${i}]: must be an object`); return; }
    if (!b.id) errs.push(`${where}: missing 'id'`);
    if (seen.has(b.id)) errs.push(`${where}: duplicate id`);
    seen.add(b.id);
    if (!TYPES.has(b.type)) { errs.push(`${where}: 'type' must be one of ${[...TYPES].sort().join(", ")}`); return; }
    if (b.status && !["confirmed", "changed", "cancelled"].includes(b.status)) errs.push(`${where}: bad 'status'`);
    const needDt = (k) => {
      if (!b[k]) { errs.push(`${where}: missing '${k}'`); return false; }
      try { parseDt(b[k]); return true; } catch (e) { errs.push(`${where}: ${k}: ${e.message}`); return false; }
    };
    if (TRANSPORT.has(b.type)) {
      const ok = needDt("depart") & needDt("arrive");
      if (b.type === "flight") {
        for (const k of ["from", "to"]) if (!/^[A-Z]{3}$/.test(String(b[k] || ""))) errs.push(`${where}: '${k}' must be a 3-letter IATA airport code`);
      } else {
        for (const k of ["from", "to"]) if (!b[k]) errs.push(`${where}: missing '${k}'`);
      }
      if (ok && parseDt(b.arrive).ms < parseDt(b.depart).ms) errs.push(`${where}: arrive is before depart`);
      if (b.previous) for (const k of ["depart", "arrive"]) if (b.previous[k]) {
        try { parseDt(b.previous[k]); } catch (e) { errs.push(`${where}: previous.${k}: ${e.message}`); }
      }
    } else if (b.type === "hotel") {
      for (const k of ["name", "city", "checkIn", "checkOut"]) if (!b[k]) errs.push(`${where}: missing '${k}'`);
      if (!isDate(b.checkIn) || !isDate(b.checkOut)) errs.push(`${where}: checkIn/checkOut must be YYYY-MM-DD`);
      else if (b.checkOut <= b.checkIn) errs.push(`${where}: checkOut must be after checkIn`);
      if (b.latestCheckIn && !/^\d{2}:\d{2}$/.test(b.latestCheckIn)) errs.push(`${where}: latestCheckIn must be HH:MM`);
    } else {
      if (needDt("start") && b.end) needDt("end");
      if (!b.name) errs.push(`${where}: missing 'name'`);
    }
  });
  return errs;
}

// ---------------------------------------------------------------- items

function toItem(b) {
  const t = b.type;
  if (TRANSPORT.has(t)) {
    const s = parseDt(b.depart), e = parseDt(b.arrive);
    return { raw: b, type: t, s, e, sd: s.date, ed: e.date, from: b.fromCity || b.from || "", to: b.toCity || b.to || "" };
  }
  if (t === "hotel") {
    // Dates only: neutral anchors 15:00 / 11:00 UTC for ordering (same as wayfare.py).
    const s = { ms: Date.parse(b.checkIn + "T15:00:00Z"), date: b.checkIn, hm: "15:00" };
    const e = { ms: Date.parse(b.checkOut + "T11:00:00Z"), date: b.checkOut, hm: "11:00" };
    return { raw: b, type: t, s, e, sd: b.checkIn, ed: b.checkOut, from: b.city, to: b.city };
  }
  const s = parseDt(b.start);
  const e = b.end ? parseDt(b.end) : { ms: s.ms + 2 * 3600000, date: s.date, hm: s.hm };
  return { raw: b, type: t, s, e, sd: s.date, ed: e.date, from: b.city || "", to: b.city || "" };
}

export function titleOf(it) {
  const r = it.raw;
  if (it.type === "flight") return `${r.carrier || ""} ${r.flightNumber || ""}`.trim() || `${r.from}→${r.to}`;
  if (it.type === "train" || it.type === "transfer") {
    return r.name || `${it.type[0].toUpperCase()}${it.type.slice(1)} ${it.from} → ${it.to}`;
  }
  return r.name || it.type;
}

const homeDep = (it, p) => (it.type === "flight" && p.homeAirports.includes(it.raw.from)) ||
  (TRANSPORT.has(it.type) && !!p.homeCity && norm(it.from) === norm(p.homeCity));
const homeArr = (it, p) => (it.type === "flight" && p.homeAirports.includes(it.raw.to)) ||
  (TRANSPORT.has(it.type) && !!p.homeCity && norm(it.to) === norm(p.homeCity));

export function groupTrips(items, p) {
  items = [...items].sort((a, b) => a.s.ms - b.s.ms || a.e.ms - b.e.ms);
  const hasHome = p.homeAirports.length > 0 || !!p.homeCity;
  const trips = [];
  let cur = null;
  for (const it of items) {
    if (!cur) { cur = { items: [], closed: false }; trips.push(cur); }
    else if (hasHome) {
      if (cur.closed || (homeDep(it, p) && cur.items.some((x) => homeDep(x, p)))) { cur = { items: [], closed: false }; trips.push(cur); }
    } else if (it.s.ms - Math.max(...cur.items.map((x) => x.e.ms)) > 4 * DAY) {
      cur = { items: [], closed: false }; trips.push(cur);
    }
    cur.items.push(it);
    if (hasHome && homeArr(it, p)) cur.closed = true;
  }
  return trips;
}

function tripCity(trip, p) {
  const counts = new Map();
  for (const it of trip.items) if (it.type === "hotel") counts.set(it.to, (counts.get(it.to) || 0) + dayNum(it.ed) - dayNum(it.sd));
  if (counts.size) return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
  const away = trip.items.find((it) => TRANSPORT.has(it.type) && !homeArr(it, p));
  return (away && away.to) || trip.items[0].to || "Trip";
}

export function lodgingGaps(trip, p) {
  const transport = trip.items.filter((i) => TRANSPORT.has(i.type));
  if (!transport.length) return [];
  const firstArrival = transport.find((i) => !homeArr(i, p)) || transport[0];
  const back = transport.filter((i) => homeArr(i, p));
  const lastDay = back.length ? back[back.length - 1].sd : trip.items.map((i) => i.ed).sort().at(-1);
  const nights = [];
  for (let d = firstArrival.ed; d < lastDay; d = addDays(d, 1)) {
    const covered = trip.items.some((it) => (it.type === "hotel" || TRANSPORT.has(it.type)) && it.sd <= d && d < it.ed);
    if (!covered) nights.push(d);
  }
  const groups = [];
  for (const n of nights) {
    const g = groups.at(-1);
    if (g && addDays(g.last, 1) === n) g.last = n; else groups.push({ first: n, last: n });
  }
  return groups.map((g) => {
    let city = "";
    const anchor = Date.parse(g.first + "T23:00:00Z");
    for (const it of [...trip.items].sort((a, b) => a.e.ms - b.e.ms)) if (it.e.ms <= anchor || it.ed <= g.first) city = it.to || city;
    const n = dayNum(g.last) - dayNum(g.first) + 1;
    return {
      kind: "lodging_gap", city, firstNight: g.first, lastNight: g.last, nights: n,
      label: `${plural(n, "night")} with no stay booked${city ? " in " + city : ""} · ${rangeLabel(g.first, addDays(g.last, 1))}`,
    };
  });
}

const alert = (level, kind, title, detail, itemIds) => ({ level, kind, title, detail, itemIds });

export function findAlerts(trip, p) {
  const out = [];
  const items = [...trip.items].sort((a, b) => a.s.ms - b.s.ms);
  const transport = items.filter((i) => TRANSPORT.has(i.type));
  const mins = (a, b) => Math.floor((b - a) / 60000);

  // 1. schedule changes
  for (const it of items) {
    const prev = it.raw.previous;
    if (it.raw.status !== "changed" || !prev) continue;
    const parts = [];
    if (prev.depart) parts.push(`departs ${parseDt(prev.depart).hm} → ${it.s.hm}`);
    if (prev.arrive) parts.push(`arrives ${parseDt(prev.arrive).hm} → ${it.e.hm}`);
    out.push(alert("high", "schedule_change", `Schedule changed: ${titleOf(it)}`, parts.join("; ") + ". Check what this affects.", [it.raw.id]));
  }
  // 2. tight or impossible connections
  for (let i = 0; i + 1 < transport.length; i++) {
    const a = transport[i], b = transport[i + 1];
    const gap = mins(a.e.ms, b.s.ms);
    if (gap > 12 * 60) continue;
    if (gap < 0) {
      out.push(alert("high", "overlap", "Next departure is before you arrive",
        `${titleOf(a)} arrives ${a.e.hm}, but ${titleOf(b)} leaves ${b.s.hm}.`, [a.raw.id, b.raw.id]));
    } else if (gap < p.minConnectionMinutes) {
      out.push(alert("high", "tight_connection", `Only ${gap} min to connect`,
        `${titleOf(a)} → ${titleOf(b)}. Your minimum is ${p.minConnectionMinutes} min.`, [a.raw.id, b.raw.id]));
    }
  }
  // 3. arrival vs dinner reservations
  for (const d of items.filter((i) => i.type === "dining")) {
    const during = transport.find((t) => t.s.ms < d.s.ms && d.s.ms < t.e.ms);
    if (during) {
      out.push(alert("high", "dining_conflict", `You are still travelling at ${d.raw.name}`,
        `Table at ${d.s.hm}, but ${titleOf(during)} arrives ${during.e.hm}.`, [during.raw.id, d.raw.id]));
      continue;
    }
    const arrivals = transport.filter((t) => t.s.ms <= d.s.ms && mins(t.e.ms, d.s.ms) < 12 * 60);
    if (!arrivals.length) continue;
    const t = arrivals.reduce((x, y) => (y.e.ms > x.e.ms ? y : x));
    const gap = mins(t.e.ms, d.s.ms);
    if (gap < p.arrivalToDinnerMinutes) {
      out.push(alert("medium", "tight_dining", `${gap} min from arrival to ${d.raw.name}`,
        `${titleOf(t)} arrives ${t.e.hm}, table at ${d.s.hm}. Your buffer is ${p.arrivalToDinnerMinutes} min.`, [t.raw.id, d.raw.id]));
    }
  }
  // 4. hotels: arrival after the check-in day, or after the latest check-in time
  const hotels = items.filter((i) => i.type === "hotel");
  for (const h of hotels) {
    const into = transport.filter((t) => norm(t.to) === norm(h.to) && t.ed <= addDays(h.sd, 1) && t.sd >= addDays(h.sd, -2));
    if (!into.length) continue;
    const t = into.reduce((x, y) => (y.e.ms > x.e.ms ? y : x));
    if (t.ed > h.sd) {
      out.push(alert("high", "no_show_risk", `You arrive after your check-in day at ${h.raw.name}`,
        `Check-in is ${dayLabel(h.sd)}, but ${titleOf(t)} arrives ${dayLabel(t.ed)} · ${t.e.hm}. ` +
        "Tell the hotel, or it may cancel the stay as a no-show.", [t.raw.id, h.raw.id]));
    } else if (h.raw.latestCheckIn && t.ed === h.sd && t.e.hm > h.raw.latestCheckIn) {
      out.push(alert("high", "late_checkin", `Late arrival at ${h.raw.name}`,
        `${titleOf(t)} arrives ${t.e.hm}; latest check-in is ${h.raw.latestCheckIn}.`, [t.raw.id, h.raw.id]));
    }
  }
  // 5. two stays on the same night
  for (let i = 0; i < hotels.length; i++) for (const b of hotels.slice(i + 1)) {
    const a = hotels[i];
    const first = a.sd > b.sd ? a.sd : b.sd;
    const last = a.ed < b.ed ? a.ed : b.ed;
    if (first < last) {
      const n = dayNum(last) - dayNum(first);
      out.push(alert("medium", "double_booking", `Two stays booked for ${plural(n, "night")}`,
        `${a.raw.name} and ${b.raw.name} overlap from ${dayLabel(first)}. If this is a mistake, cancel one while it is still free to cancel.`,
        [a.raw.id, b.raw.id]));
    }
  }
  const changed = new Set(items.filter((i) => i.raw.status === "changed").map((i) => i.raw.id));
  for (const a of out) if (a.kind !== "schedule_change" && a.itemIds.some((id) => changed.has(id))) a.fromChange = true;
  const order = { high: 0, medium: 1, info: 2 };
  return out.sort((a, b) => order[a.level] - order[b.level]);
}

// Only these fields are read. Anything else (booking codes, prices, names,
// links) is dropped before the check, so it is never used or returned.
const KEEP = ["id", "type", "status", "carrier", "flightNumber", "from", "to", "fromCity", "toCity", "depart", "arrive",
  "name", "city", "checkIn", "checkOut", "latestCheckIn", "start", "end"];

function strip(b) {
  if (!b || typeof b !== "object") return b;
  const o = {};
  for (const k of KEEP) if (b[k] !== undefined) o[k] = b[k];
  if (b.previous && typeof b.previous === "object") o.previous = { depart: b.previous.depart, arrive: b.previous.arrive };
  return o;
}

export function checkItinerary(input) {
  const bookings = (input.bookings || []).map(strip);
  const errors = validate(bookings);
  if (errors.length) return { ok: false, errors };
  const p = { ...DEFAULTS, ...(input.profile || {}) };
  p.homeAirports = (p.homeAirports || []).map((x) => String(x).toUpperCase());
  const items = bookings.filter((b) => b.status !== "cancelled").map(toItem);
  const trips = groupTrips(items, p).map((t) => {
    const dates = t.items.flatMap((i) => [i.sd, i.ed]).sort();
    return {
      city: tripCity(t, p), startDate: dates[0], endDate: dates.at(-1),
      bookingIds: t.items.map((i) => i.raw.id),
      nightsWithoutStay: lodgingGaps(t, p),
      alerts: findAlerts(t, p),
    };
  });
  const counts = trips.reduce((c, t) => {
    for (const a of t.alerts) c[a.level] = (c[a.level] || 0) + 1;
    c.nightsWithoutStay += t.nightsWithoutStay.reduce((s, g) => s + g.nights, 0);
    return c;
  }, { high: 0, medium: 0, nightsWithoutStay: 0 });
  return { ok: true, trips, counts, note: "Checked only the facts you sent. Confirm important facts with the provider." };
}
