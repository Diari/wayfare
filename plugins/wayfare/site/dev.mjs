// Local preview of a Wayfare Site, without ChatGPT Sites.
//   node dev.mjs [port]          (Node 22+; uses node:sqlite as a stand-in for D1)
// Identity: set DEV_EMAIL to act as a signed-in viewer, OWNER_EMAIL for the owner.
// A request header oai-authenticated-user-email (as Sites sends it) wins over DEV_EMAIL.
import http from "node:http";
import { DatabaseSync } from "node:sqlite";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const port = Number(process.argv[2] || process.env.PORT || 8787);
const dir = resolve(process.env.SITE_DIR || ".");
const worker = (await import(pathToFileURL(resolve(dir, "worker/index.js")).href)).default;
const sqlite = new DatabaseSync(process.env.DB_FILE || ":memory:");

// The part of the D1 API the worker uses: prepare().bind().all()/first()/run().
function d1(db) {
  return {
    prepare(sql) {
      let args = [];
      const stmt = {
        bind(...a) { args = a; return stmt; },
        async all() { return { results: db.prepare(sql).all(...args), success: true }; },
        async first() { return db.prepare(sql).get(...args) ?? null; },
        async run() { const r = db.prepare(sql).run(...args); return { success: true, meta: { changes: r.changes } }; },
      };
      return stmt;
    },
  };
}
const env = { DB: d1(sqlite), OWNER_EMAIL: process.env.OWNER_EMAIL || "owner@example.com", EDITOR_EMAILS: process.env.EDITOR_EMAILS || "" };

http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) if (typeof v === "string") headers.set(k, v);
  if (!headers.get("oai-authenticated-user-email") && process.env.DEV_EMAIL) headers.set("oai-authenticated-user-email", process.env.DEV_EMAIL);
  const body = ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks);
  const r = await worker.fetch(new Request(`http://localhost:${port}${req.url}`, { method: req.method, headers, body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, () => console.log(`Wayfare Site preview on http://localhost:${port} (owner: ${env.OWNER_EMAIL})`));
