// Runs ui/sw.js, the phone's copy of the page, in Node against a stand-in Mac
// and a stand-in Cache API, and prints what it saw as JSON for test_ui.py.
// Nothing here touches the network.
//
//     node tests/sw_harness.js ui/sw.js

"use strict";

const fs = require("fs");
const vm = require("vm");

const SOURCE = fs.readFileSync(process.argv[2], "utf-8");
const ORIGIN = "https://mac.example.ts.net:8443";

// ------------------------------------------------------- the Cache API, kept in memory

const stores = new Map();   // cache name -> Map(url -> {body, status, headers})

function key(r) { return typeof r === "string" ? r : r.url; }

class Cache {
  constructor(entries) { this.entries = entries; }
  async match(r) {
    const e = this.entries.get(key(r));
    return e && new Response(e.body, { status: e.status, headers: e.headers });
  }
  async put(r, response) {
    const body = Buffer.from(await response.arrayBuffer());
    this.entries.set(key(r), { body, status: response.status, headers: [...response.headers] });
  }
  async delete(r) { return this.entries.delete(key(r)); }
  async keys() { return [...this.entries.keys()].map(url => ({ url })); }
}

const caches = {
  async open(name) { if (!stores.has(name)) stores.set(name, new Map()); return new Cache(stores.get(name)); },
  async keys() { return [...stores.keys()]; },
  async has(name) { return stores.has(name); },
  async delete(name) { return stores.delete(name); },
};

// ------------------------------------------------------------------ the Mac

const mac = { drawing: "a1", page: "<title>BS Job Search v1.90</title><body>Job Search</body>", asked: [] };

async function macFetch(input) {
  const url = new URL(key(input));
  mac.asked.push(url.pathname + url.search);
  const p = url.pathname;
  const answer = (body, type, headers = {}) =>
    new Response(body, { status: 200, headers: { "Content-Type": type, ...headers } });
  if (p === "/") return answer(mac.page, "text/html", { ETag: `"${mac.page.length}"` });
  if (p === "/app.js" || p === "/style.css") return answer("code", "text/javascript", { ETag: '"1"' });
  if (p === "/manifest.webmanifest") return answer(`{"drawing": "${mac.drawing}"}`, "application/manifest+json");
  if (p.endsWith(".png")) return answer(`${p.slice(1)} drawn as ${mac.drawing}`, "image/png");
  if (p === "/api/snapshot") return answer(JSON.stringify({ etag: "s1", answers: { "/api/digests": [] } }), "application/json");
  return new Response("not found", { status: 404 });
}

// --------------------------------------------------------------- a worker

function worker(icons) {
  const listeners = {};
  const told = [];
  const state = { unregistered: false };
  const self = {
    location: { href: ORIGIN + "/sw.js" },
    addEventListener: (type, fn) => { listeners[type] = fn; },
    skipWaiting: async () => {},
    registration: { unregister: async () => { state.unregistered = true; return true; } },
    clients: { claim: async () => {}, matchAll: async () => [{ postMessage: m => told.push(m) }] },
  };
  const script = SOURCE.replace('const ICONS = "";', `const ICONS = "${icons}";`);
  vm.runInContext(script, vm.createContext({
    self, caches, fetch: macFetch, Response, Headers, Request, URL, AbortController,
    setTimeout, clearTimeout, console,
  }));

  async function lifecycle(type, data) {
    const waits = [];
    const event = { data, source: { postMessage: m => told.push(m) }, waitUntil: p => waits.push(p) };
    listeners[type](event);
    await Promise.all(waits);
  }

  // A GET through the worker: what answered, its text, and whether it was the copy's.
  async function get(path) {
    const waits = [];
    let answer = null;
    const event = { request: new Request(ORIGIN + path), waitUntil: p => waits.push(p), respondWith: p => { answer = p; } };
    const before = mac.asked.length;
    listeners.fetch(event);
    if (!answer) return { path, intercepted: false };
    const r = await answer;
    const text = await r.text();
    await Promise.all(waits);
    return { path, intercepted: true, status: r.status, text, asked: mac.asked.slice(before) };
  }

  return { lifecycle, get, told, state };
}

function stored() {
  const out = {};
  for (const [name, entries] of stores) out[name] = [...entries.keys()].map(u => u.slice(ORIGIN.length));
  return out;
}

// ---------------------------------------------------------------- the story

(async () => {
  const seen = {};

  // A phone installs the worker while the icon is drawing a1.
  const first = worker("a1");
  await first.lifecycle("install");
  await first.lifecycle("activate");
  await first.lifecycle("message", { type: "settings", profile: false, documents: false });
  seen.installed = stored();
  seen.icon = await first.get("/favicon.png?v=a1");
  seen.older = await first.get("/favicon.png?v=0ld");
  seen.bare = await first.get("/favicon.png");
  seen.fromIcon = await first.get("/?from=icon");

  // The drawing changes: the server stamps a new worker, which the phone installs.
  mac.drawing = "b2";
  const second = worker("b2");
  await second.lifecycle("install");
  await second.lifecycle("activate");
  seen.redrawn = stored();
  seen.newIcon = await second.get("/favicon.png?v=b2");
  seen.touchIcon = await second.get("/apple-touch-icon.png?v=b2");
  seen.oldIcon = await second.get("/favicon.png?v=a1");
  seen.settings = await (await (await caches.open("bs-job-search-1")).match(ORIGIN + "/__settings")).json();

  // Another app is set up at this address: its page, not Job Search's.
  mac.page = "<title>Personal Finance</title>";
  seen.takenOver = await second.get("/");
  seen.afterTakeover = await second.get("/favicon.png?v=b2");
  seen.unregistered = second.state.unregistered;
  seen.told = second.told.map(m => m.type);
  seen.left = stored();

  process.stdout.write(JSON.stringify(seen));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
