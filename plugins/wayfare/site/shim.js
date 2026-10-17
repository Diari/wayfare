// Wayfare Sites adapter. The trip and home pages are shared with the Claude
// version, which talks to a `window.claude` database. On ChatGPT Sites this
// file provides the same small interface on top of the Site's own API
// (/api/state and friends), so one page works in both places.
(function () {
  "use strict";
  var cache = null, listeners = [];
  function emit() { listeners.slice().forEach(function (f) { try { f(); } catch (e) {} }); }
  function load() {
    return fetch("/api/state", { credentials: "same-origin", headers: { accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (s) { cache = s; emit(); notes(); return s; });
  }
  setInterval(function () { if (!document.hidden) load().catch(function () {}); }, 60000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) load().catch(function () {}); });

  function docValue(path) {
    if (!cache) return undefined;
    var m;
    if (path === "trip/data") return cache.trip;
    if (path === "private/data") return cache.private;
    if (path === "guide/data") return cache.guide;
    if (path === "index/trips") return cache.index;
    if ((m = path.match(/^actions\/(.+)$/))) return cache.actions && cache.actions[m[1]];
    if ((m = path.match(/^todos\/(.+)$/))) return (cache.todos || []).filter(function (t) { return t.id === m[1]; })[0];
    if (/^data\/users\/[^/]+\/packing$/.test(path)) return { done: cache.packing || [] };
    return null;
  }
  function snap(path) { var v = docValue(path); return { id: path.split("/").pop(), exists: v != null, data: function () { return v; } }; }
  function rows(path) {
    if (!cache) return [];
    if (path === "actions") return Object.keys(cache.actions || {}).map(function (k) { return [k, cache.actions[k]]; });
    if (path === "todos") return (cache.todos || []).map(function (t) { return [t.id, t]; });
    return [];
  }
  function api(method, url, body) {
    return fetch(url, { method: method, credentials: "same-origin", headers: { "content-type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) throw { code: r.status === 401 ? "not_signed_in" : "denied", message: j.error || "Request failed" };
          return j;
        });
      })
      .then(function (j) { return load().then(function () { return j; }); });
  }
  function write(path, op, d) {
    var m;
    if ((m = path.match(/^actions\/(.+)$/))) {
      return op === "delete" ? api("DELETE", "/api/actions/" + encodeURIComponent(m[1])) : api("PUT", "/api/actions/" + encodeURIComponent(m[1]), d);
    }
    if ((m = path.match(/^todos\/(.+)$/))) {
      return op === "delete" ? api("DELETE", "/api/todos/" + encodeURIComponent(m[1])) : api("PATCH", "/api/todos/" + encodeURIComponent(m[1]), { done: !!(d && d.done) });
    }
    if (/^data\/users\/[^/]+\/packing$/.test(path)) return api("PUT", "/api/packing", { done: (d && d.done) || [] });
    return Promise.reject({ code: "not_supported" });
  }
  function docRef(path) {
    return {
      id: path.split("/").pop(), path: path,
      get: function () { return (cache ? Promise.resolve() : load()).then(function () { return snap(path); }); },
      onSnapshot: function (next) {
        var f = function () { if (cache) next(snap(path)); };
        listeners.push(f); f();
        return function () { listeners = listeners.filter(function (x) { return x !== f; }); };
      },
      set: function (d) { return write(path, "set", d); },
      update: function (d) { return write(path, "update", d); },
      delete: function () { return write(path, "delete"); }
    };
  }
  function collRef(path) {
    return {
      path: path,
      doc: function (id) { return docRef(path + "/" + id); },
      add: function (d) {
        if (path !== "todos") return Promise.reject({ code: "not_supported" });
        return api("POST", "/api/todos", { text: d && d.text }).then(function (j) { return docRef("todos/" + j.id); });
      },
      onSnapshot: function (next) {
        var f = function () {
          if (!cache) return;
          var docs = rows(path).map(function (p) { return { id: p[0], exists: true, data: function () { return p[1]; } }; });
          next({ docs: docs, size: docs.length, empty: !docs.length });
        };
        listeners.push(f); f();
        return function () { listeners = listeners.filter(function (x) { return x !== f; }); };
      }
    };
  }
  var db = { doc: docRef, collection: collRef };
  var ready = load().catch(function () { return null; });
  var user = {
    isOwner: function () { return ready.then(function () { return !!(cache && cache.me && cache.me.isOwner); }); },
    canEdit: function () { return ready.then(function () { return !!(cache && cache.me && cache.me.canEdit); }); },
    id: function () { return ready.then(function () { return cache && cache.me && cache.me.signedIn ? "me" : null; }); }
  };
  window.claude = { use: function (name) { return ready.then(function () { return name === "db" ? db : name === "user" ? user : null; }); } };
  window.WAYFARE_SITE = { ics: "/trip.ics", signIn: "/signin-with-chatgpt" };

  // A quiet note for people who are not signed in, and for Home when the viewer is not the owner.
  function notes() {
    if (!cache || !document.body) return;
    var id = "wayfare-site-note", el = document.getElementById(id);
    var text = null, link = null;
    if (cache.denied) text = "Only the owner can see Wayfare Home.";
    else if (cache.me && !cache.me.signedIn && cache.kind === "trip") { text = "Sign in to tick to-dos and keep your own packing list."; link = "Sign in with ChatGPT"; }
    if (!text) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div"); el.id = id;
      el.setAttribute("role", "note");
      el.style.cssText = "position:fixed;left:16px;right:16px;bottom:16px;max-width:560px;margin:0 auto;background:var(--ink,#1c2330);color:var(--bg,#fff);border-radius:14px;padding:12px 16px;font:500 14px/1.4 system-ui,sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.2);z-index:50;display:flex;gap:4px 12px;align-items:center;flex-wrap:wrap;justify-content:space-between";
      document.body.appendChild(el);
    }
    el.textContent = text;
    if (link) {
      var a = document.createElement("a"); a.href = "/signin-with-chatgpt"; a.textContent = link;
      a.style.cssText = "color:inherit;font-weight:700;text-decoration:underline;white-space:nowrap";
      el.appendChild(a);
    }
  }

  // Site tools (WebMCP): when the page is open in the ChatGPT app's browser,
  // ChatGPT can read the trip and act on it through these narrow tools.
  function registerTools() {
    var mc = document.modelContext;
    if (!mc || typeof mc.registerTool !== "function") return;
    function openIssues() {
      var t = cache && cache.trip; if (!t) return [];
      return (t.alerts || []).filter(function (a) {
        var act = cache.actions && cache.actions[a.id];
        return !(act && act.fingerprint === a.fingerprint && (act.status !== "snoozed" || new Date(act.until) > new Date()));
      }).map(function (a) { return { id: a.id, level: a.level, title: a.title, detail: a.detail }; });
    }
    var tools = [
      { name: "wayfare_trip_summary", description: "Read this trip: title, dates, places, bookings by day and open problems. Booking codes are masked.",
        inputSchema: { type: "object", properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true },
        execute: function () {
          var t = cache && cache.trip; if (!t) return { error: "not loaded" };
          return { title: t.pageTitle, dates: t.dates, travellers: t.travellers, days: t.days,
            bookings: (t.items || []).map(function (i) { return { day: i.day, type: i.type, title: i.title, when: i.when, until: i.until }; }),
            openProblems: openIssues(), todos: (cache.todos || []).map(function (x) { return { text: x.text, done: x.done }; }) };
        } },
      { name: "wayfare_mark_problem", description: "Mark one open problem on this trip as handled, not a problem, or 'remind me in 3 days'. Only the owner and editors can do this.",
        inputSchema: { type: "object", properties: { problemId: { type: "string" }, status: { type: "string", enum: ["done", "ignored", "snoozed"] } }, required: ["problemId", "status"], additionalProperties: false },
        execute: function (input) {
          var a = ((cache && cache.trip && cache.trip.alerts) || []).filter(function (x) { return x.id === input.problemId; })[0];
          if (!a) return { error: "unknown problem id" };
          var body = { alertId: a.id, fingerprint: a.fingerprint, status: input.status, title: a.title };
          if (input.status === "snoozed") body.until = new Date(Date.now() + 3 * 864e5).toISOString();
          return api("PUT", "/api/actions/" + encodeURIComponent(a.id), body).then(function () { return { ok: true, problem: a.title, status: input.status }; });
        } },
      { name: "wayfare_add_todo", description: "Add one item to this trip's shared to-do list.",
        inputSchema: { type: "object", properties: { text: { type: "string", maxLength: 200 } }, required: ["text"], additionalProperties: false },
        execute: function (input) { return api("POST", "/api/todos", { text: input.text }).then(function (j) { return { ok: true, id: j.id }; }); } }
    ];
    tools.forEach(function (t) { try { mc.registerTool(t); } catch (e) {} });
  }
  ready.then(registerTools);
})();
