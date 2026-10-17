import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import worker from "../src/index.js";
import { TOOLS, handleRpc } from "../src/server.js";
import { checkItinerary } from "../src/itinerary.js";
import { tripWeather, shiftYear } from "../src/weather.js";
import { packingList } from "../src/packing.js";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const SAMPLES = ROOT + "plugins/wayfare-claude/samples/";
const bookings = JSON.parse(readFileSync(SAMPLES + "bookings.sample.json", "utf8"));
const profile = JSON.parse(readFileSync(SAMPLES + "profile.sample.json", "utf8"));
const unwrap = (x) => (Array.isArray(x) ? x : x.bookings || x.data || x);
const prof = profile.profile || profile;

async function rpc(body) {
  const r = await worker.fetch(new Request("https://x.test/mcp", {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
    body: JSON.stringify(body),
  }), {});
  return { status: r.status, body: r.status === 202 ? null : await r.json() };
}

test("initialize, notifications, list and unknown method", async () => {
  const init = await rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "1" } } });
  assert.equal(init.body.result.protocolVersion, "2025-06-18");
  assert.equal(init.body.result.serverInfo.name, "wayfare");
  const old = await rpc({ jsonrpc: "2.0", id: 9, method: "initialize", params: { protocolVersion: "1999-01-01" } });
  assert.equal(old.body.result.protocolVersion, "2025-06-18");
  assert.equal((await rpc({ jsonrpc: "2.0", method: "notifications/initialized" })).status, 202);
  const list = await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  assert.deepEqual(list.body.result.tools.map((t) => t.name), ["check_itinerary", "get_trip_weather", "get_packing_list"]);
  for (const t of list.body.result.tools) {
    assert.equal(t.annotations.readOnlyHint, true);
    assert.equal(t.annotations.destructiveHint, false);
    assert.equal(typeof t.annotations.openWorldHint, "boolean");
    assert.ok(t.description.length < 1024);
  }
  assert.equal((await rpc({ jsonrpc: "2.0", id: 3, method: "nope" })).body.error.code, -32601);
  assert.equal((await rpc({ jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "book_hotel" } })).body.error.code, -32602);
});

test("GET is refused and the challenge route uses the secret", async () => {
  assert.equal((await worker.fetch(new Request("https://x.test/mcp"), {})).status, 405);
  assert.equal(await (await worker.fetch(new Request("https://x.test/.well-known/openai-apps-challenge"), {})).text(), "9vxESZGyY3x_c99tOQHiv4VdJ_zxbfUlylg223RKpDU");
  const r = await worker.fetch(new Request("https://x.test/.well-known/openai-apps-challenge"), { OPENAI_APPS_CHALLENGE: "abc123\n" });
  assert.equal(await r.text(), "abc123");
});

test("check_itinerary matches the Python engine on the samples", async () => {
  const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(ROOT + "plugins/wayfare-claude/scripts")})
import wayfare as w
b = w.unwrap(json.load(open(${JSON.stringify(SAMPLES + "bookings.sample.json")})))
p = dict(w.DEFAULT_PROFILE); p.update(w.unwrap(json.load(open(${JSON.stringify(SAMPLES + "profile.sample.json")}))))
items = [w.to_item(x) for x in b if x.get("status") != "cancelled"]
out = []
for t in w.group_trips(items, p):
    out.append({"gaps": [[g["firstNight"], g["nights"], g["city"]] for g in w.lodging_gaps(t, p)],
                "alerts": sorted([a["kind"], a["title"], tuple(a["itemIds"])] for a in w.find_alerts(t, p, {}) )})
print(json.dumps(out))`;
  const expected = JSON.parse(execFileSync("python3", ["-c", py], { encoding: "utf8" }));
  const r = checkItinerary({ bookings: unwrap(bookings), profile: prof });
  assert.equal(r.ok, true, JSON.stringify(r.errors));
  const got = r.trips.map((t) => ({
    gaps: t.nightsWithoutStay.map((g) => [g.firstNight, g.nights, g.city]),
    alerts: t.alerts.map((a) => [a.kind, a.title, a.itemIds]).sort(),
  }));
  assert.deepEqual(JSON.parse(JSON.stringify(got)), JSON.parse(JSON.stringify(expected)));
  assert.ok(got.some((t) => t.alerts.length > 0), "samples should produce alerts");
});

test("check_itinerary drops private fields and reports bad input as a tool error", async () => {
  const b = [{ id: "h1", type: "hotel", name: "A", city: "Rome", checkIn: "2026-11-01", checkOut: "2026-11-03",
    confirmation: "ABC123", price: { amount: 300, currency: "EUR" }, manageUrl: "https://x.example/m" },
  { id: "h2", type: "hotel", name: "B", city: "Rome", checkIn: "2026-11-02", checkOut: "2026-11-04" }];
  const ok = await rpc({ jsonrpc: "2.0", id: 5, method: "tools/call", params: { name: "check_itinerary", arguments: { bookings: b } } });
  const text = ok.body.result.content[0].text;
  assert.ok(!text.includes("ABC123") && !text.includes("300") && !text.includes("x.example"));
  assert.equal(ok.body.result.structuredContent.trips[0].alerts[0].kind, "double_booking");
  const bad = await rpc({ jsonrpc: "2.0", id: 6, method: "tools/call", params: { name: "check_itinerary", arguments: { bookings: [{ id: "x", type: "flight", depart: "tomorrow" }] } } });
  assert.equal(bad.body.result.isError, true);
});

function fakeOpenMeteo(calls) {
  return async (url) => {
    calls.push(url);
    const u = new URL(url);
    if (u.hostname.startsWith("geocoding")) return Response.json({ results: [{ name: "Lisbon", country: "Portugal", latitude: 38.7, longitude: -9.1, timezone: "Europe/Lisbon" }] });
    const start = u.searchParams.get("start_date"), end = u.searchParams.get("end_date");
    const time = [];
    for (let d = new Date(start + "T00:00:00Z"); d <= new Date(end + "T00:00:00Z"); d = new Date(+d + 86400000)) time.push(d.toISOString().slice(0, 10));
    const archive = u.hostname.startsWith("archive");
    return Response.json({ daily: { time, temperature_2m_max: time.map(() => 27.4), temperature_2m_min: time.map(() => 3.6),
      weather_code: time.map(() => 61), [archive ? "precipitation_sum" : "precipitation_probability_max"]: time.map(() => (archive ? 4 : 70)) } });
  };
}

test("get_trip_weather splits forecast and last year", async () => {
  const calls = [];
  const r = await tripWeather({ city: "Lisbon", start_date: "2026-10-30", end_date: "2026-11-05" }, { fetcher: fakeOpenMeteo(calls), today: "2026-10-17" });
  assert.equal(r.ok, true);
  assert.equal(r.days.length, 7);
  assert.equal(r.days[0].kind, "forecast");
  assert.equal(r.days.at(-1).kind, "lastYear");
  assert.ok(calls.some((c) => c.includes("archive-api") && c.includes("start_date=2025-11-02")));
  assert.equal((await tripWeather({ city: "Lisbon", start_date: "2026-01-01", end_date: "2026-03-01" }, { fetcher: fakeOpenMeteo([]), today: "2026-01-01" })).ok, false);
  assert.equal(shiftYear("2028-02-29"), "2027-02-28");
  assert.equal(shiftYear("2026-11-02"), "2025-11-02");
});

test("packing list follows weather and plans", () => {
  const cold = packingList({ start_date: "2026-12-01", end_date: "2026-12-11", activities: ["business"],
    weather: { hi: 27, lo: 3, wetDays: 5, days: 10, snow: true } });
  const ids = cold.groups.flatMap((g) => g.items.map((i) => i.id));
  for (const id of ["coat", "sunscreen", "umbrella", "rainjacket", "boots", "laptop", "adapter"]) assert.ok(ids.includes(id), id);
  assert.equal(cold.nights, 10);
  assert.ok(cold.tips[0].includes("laundry"));
  const home = packingList({ start_date: "2026-12-01", end_date: "2026-12-02", international: false });
  assert.ok(!home.groups.flatMap((g) => g.items).some((i) => i.id === "adapter"));
});

test("tool list is stable", () => {
  assert.equal(TOOLS.length, 3);
  assert.ok(handleRpc);
});
