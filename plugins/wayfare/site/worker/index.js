// Wayfare Site worker (ChatGPT Sites, Cloudflare Worker-compatible ES module).
//
// One Site per trip, plus one "Wayfare Home" Site. The trip facts are baked
// into ./data.js at build time (Codex rewrites it and redeploys after each
// check). What people do on the page (handled marks, to-dos, packing ticks)
// lives in the Site's D1 database (binding "DB"), so a redeploy keeps it.
//
// Identity: Sites forwards the signed-in viewer in request headers
// (oai-authenticated-user-email, oai-authenticated-user-full-name). The owner
// is the email in the OWNER_EMAIL environment value; EDITOR_EMAILS (comma
// separated) may mark problems handled. Full booking codes and manage links
// are served to the owner only.

import PAGE from "./page.js";
import DATA from "./data.js";

const ID_RE = /^[A-Za-z0-9_.:-]{1,120}$/;
const MAX_TODOS = 200;
let schemaReady = false;

const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS actions (alert_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, until TEXT, title TEXT, by_email TEXT, at TEXT NOT NULL)",
  "CREATE TABLE IF NOT EXISTS todos (id TEXT PRIMARY KEY, text TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, by_email TEXT, at TEXT NOT NULL, done_at TEXT)",
  "CREATE TABLE IF NOT EXISTS packing (email TEXT NOT NULL, item_id TEXT NOT NULL, PRIMARY KEY (email, item_id))",
];

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", "x-content-type-options": "nosniff" },
  });
}
const fail = (status, error) => json({ error }, status);

export function who(request, env) {
  const email = (request.headers.get("oai-authenticated-user-email") || "").trim().toLowerCase();
  const owner = (env.OWNER_EMAIL || "").trim().toLowerCase();
  const editors = (env.EDITOR_EMAILS || "").toLowerCase().split(",").map((s) => s.trim()).filter(Boolean);
  const isOwner = !!email && !!owner && email === owner;
  return {
    email: email || null,
    name: (request.headers.get("oai-authenticated-user-full-name") || "").trim() || email || null,
    isOwner,
    canEdit: isOwner || (!!email && editors.includes(email)),
  };
}

async function ensureSchema(db) {
  if (schemaReady) return;
  for (const sql of SCHEMA) await db.prepare(sql).run();
  schemaReady = true;
}

async function readBody(request) {
  const type = request.headers.get("content-type") || "";
  if (!type.includes("application/json")) throw new Error("expected JSON");
  const text = await request.text();
  if (text.length > 20000) throw new Error("body too large");
  return text ? JSON.parse(text) : {};
}

function sameOrigin(request) {
  const origin = request.headers.get("origin");
  if (!origin) return true; // same-origin fetches from older browsers, and server tools
  try { return new URL(origin).host === new URL(request.url).host; } catch { return false; }
}

async function state(env, me) {
  const db = env.DB;
  const out = { kind: DATA.kind, me: { signedIn: !!me.email, name: me.name, isOwner: me.isOwner, canEdit: me.canEdit } };
  if (DATA.kind === "home") {
    // Wayfare Home lists every trip: owner only.
    if (!me.isOwner) return { ...out, index: null, denied: true };
    return { ...out, index: DATA.index, plans: DATA.plans || null, agent: null };
  }
  if (DATA.kind === "plan") {
    // A trip not booked yet: wishes, options and prices. No booking codes.
    return { ...out, plan: DATA.plan };
  }
  out.trip = DATA.trip;
  out.guide = DATA.guide || null;
  out.private = me.isOwner ? DATA.private || null : null;
  const acts = await db.prepare("SELECT alert_id, fingerprint, status, until, title, by_email, at FROM actions").all();
  out.actions = {};
  for (const r of acts.results || []) {
    out.actions[r.alert_id] = { alertId: r.alert_id, fingerprint: r.fingerprint, status: r.status, until: r.until, title: r.title, at: r.at };
  }
  const todos = await db.prepare("SELECT id, text, done, at, done_at FROM todos ORDER BY at LIMIT ?").bind(MAX_TODOS).all();
  out.todos = (todos.results || []).map((r) => ({ id: r.id, text: r.text, done: !!r.done, at: r.at, doneAt: r.done_at }));
  out.packing = [];
  if (me.email) {
    const p = await db.prepare("SELECT item_id FROM packing WHERE email = ?").bind(me.email).all();
    out.packing = (p.results || []).map((r) => r.item_id);
  }
  return out;
}

// ---------- calendar file ----------
function icsEscape(s) { return String(s || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n"); }
function icsTime(iso) {
  const d = new Date(iso);
  return d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}
export function ics(trip, host) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Wayfare//Trip//EN", "CALSCALE:GREGORIAN", "X-WR-CALNAME:" + icsEscape(trip.pageTitle || trip.title)];
  const stamp = icsTime(new Date().toISOString());
  for (const it of trip.items || []) {
    const c = it.calendar;
    if (!c) continue;
    lines.push("BEGIN:VEVENT", "UID:" + icsEscape(it.id) + "@" + host, "DTSTAMP:" + stamp);
    if (c.allDay) {
      lines.push("DTSTART;VALUE=DATE:" + c.start.replace(/-/g, ""), "DTEND;VALUE=DATE:" + c.end.replace(/-/g, ""));
    } else {
      lines.push("DTSTART:" + icsTime(c.start), "DTEND:" + icsTime(c.end));
    }
    lines.push("SUMMARY:" + icsEscape(c.summary), "LOCATION:" + icsEscape(c.location), "DESCRIPTION:" + icsEscape("From your Wayfare trip page."), "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map((l) => (l.length > 74 ? l.match(/.{1,74}/g).join("\r\n ") : l)).join("\r\n") + "\r\n";
}

// ---------- router ----------
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const me = who(request, env);
    try {
      if (request.method === "GET" && (path === "/" || path === "/index.html")) {
        return new Response(PAGE, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-frame-options": "SAMEORIGIN" } });
      }
      if (request.method === "GET" && path === "/trip.ics" && DATA.kind === "trip") {
        return new Response(ics(DATA.trip, url.host), { headers: { "content-type": "text/calendar; charset=utf-8", "content-disposition": `attachment; filename="${(DATA.trip.slug || "trip").replace(/[^a-z0-9-]/g, "")}.ics"` } });
      }
      if (!path.startsWith("/api/")) return new Response("Not found", { status: 404 });
      if (!env.DB) return fail(500, "The site has no database. Add a D1 database named DB.");
      await ensureSchema(env.DB);
      if (request.method === "GET" && path === "/api/state") return json(await state(env, me));
      if (request.method !== "GET" && !sameOrigin(request)) return fail(403, "cross-site request");
      if (DATA.kind !== "trip") return fail(404, "not found");

      // Problems: handled / not a problem / later (owner and editors)
      let m = path.match(/^\/api\/actions\/([^/]+)$/);
      if (m) {
        const id = decodeURIComponent(m[1]);
        if (!ID_RE.test(id)) return fail(400, "bad id");
        if (!me.canEdit) return fail(403, "Only the trip owner and editors can do this.");
        if (request.method === "PUT") {
          const b = await readBody(request);
          if (!["done", "ignored", "snoozed"].includes(b.status) || typeof b.fingerprint !== "string") return fail(400, "bad action");
          const now = new Date().toISOString();
          await env.DB.prepare("INSERT INTO actions (alert_id, fingerprint, status, until, title, by_email, at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(alert_id) DO UPDATE SET fingerprint=excluded.fingerprint, status=excluded.status, until=excluded.until, title=excluded.title, by_email=excluded.by_email, at=excluded.at")
            .bind(id, b.fingerprint.slice(0, 40), b.status, b.status === "snoozed" ? String(b.until || "").slice(0, 40) : null, String(b.title || "").slice(0, 200), me.email, now).run();
          return json({ ok: true });
        }
        if (request.method === "DELETE") {
          await env.DB.prepare("DELETE FROM actions WHERE alert_id = ?").bind(id).run();
          return json({ ok: true });
        }
      }
      // To-dos: any signed-in viewer adds and ticks; the owner removes
      if (path === "/api/todos" && request.method === "POST") {
        if (!me.email) return fail(401, "Sign in to add to-dos.");
        const b = await readBody(request);
        const text = String(b.text || "").trim().slice(0, 200);
        if (!text) return fail(400, "empty");
        const count = await env.DB.prepare("SELECT COUNT(*) AS n FROM todos").first();
        if ((count && count.n) >= MAX_TODOS) return fail(400, "too many to-dos");
        const id = "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        await env.DB.prepare("INSERT INTO todos (id, text, done, by_email, at) VALUES (?, ?, 0, ?, ?)").bind(id, text, me.email, new Date().toISOString()).run();
        return json({ ok: true, id });
      }
      m = path.match(/^\/api\/todos\/([^/]+)$/);
      if (m) {
        const id = decodeURIComponent(m[1]);
        if (!ID_RE.test(id)) return fail(400, "bad id");
        if (request.method === "PATCH") {
          if (!me.email) return fail(401, "Sign in to tick to-dos.");
          const b = await readBody(request);
          await env.DB.prepare("UPDATE todos SET done = ?, done_at = ? WHERE id = ?").bind(b.done ? 1 : 0, b.done ? new Date().toISOString() : null, id).run();
          return json({ ok: true });
        }
        if (request.method === "DELETE") {
          if (!me.isOwner) return fail(403, "Only the trip owner can remove to-dos.");
          await env.DB.prepare("DELETE FROM todos WHERE id = ?").bind(id).run();
          return json({ ok: true });
        }
      }
      // Packing ticks: private to each signed-in person
      if (path === "/api/packing" && request.method === "PUT") {
        if (!me.email) return fail(401, "Sign in to keep your packing list.");
        const b = await readBody(request);
        const ids = (Array.isArray(b.done) ? b.done : []).map(String).filter((x) => /^[a-z0-9-]{1,40}$/.test(x)).slice(0, 60);
        await env.DB.prepare("DELETE FROM packing WHERE email = ?").bind(me.email).run();
        for (const x of ids) await env.DB.prepare("INSERT OR IGNORE INTO packing (email, item_id) VALUES (?, ?)").bind(me.email, x).run();
        return json({ ok: true });
      }
      return fail(404, "not found");
    } catch (e) {
      return fail(400, String((e && e.message) || e).slice(0, 200));
    }
  },
};
