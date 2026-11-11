// The phone's copy of this page. app.js registers this worker only off the
// Mac, so on a phone reaching the page through Tailscale (ui/phone.py). It
// keeps the page's own files and what the page reads, so the icon opens and
// shows the digests, the applications and the profile files while the Mac
// cannot be reached: asleep, offline, or with Tailscale off on either side.
//
// The copy is the Cache API: the page's files, and one entry per read the Mac
// answers from /api/snapshot (core.snapshot). This phone's choices, in the
// Setup tab, decide two things: whether the profile files' text is kept (yes
// unless turned off), and whether documents filed in the last 30 days are
// (no unless turned on; they carry contact details). Never keys, contact.local.md,
// run transcripts, or what Setup and Runs show, which need the Mac anyway.
// Forget this phone's copy deletes all of it and the worker too. Writes go to
// the Mac; app.js keeps those it could not send in its outbox.
//
// A read asks the Mac first while it has answered lately, and falls back to
// the copy. When it has not, the copy answers at once and the Mac is asked in
// the background, so the icon opens without waiting on a Mac that may be
// asleep; an answer from the copy carries X-Served-From: phone and X-Saved-At,
// and the page shows the age. Whenever the Mac answers something newer, the
// page is told ("fresh", or "page" for its own files) and redraws.
//
// The icons and the manifest are kept by the address the page names them by,
// ?v=<the drawing's fingerprint> and all (icon.stamp), which the server writes
// into this file as ICONS (icon.stamp_worker). One address is one drawing for
// good, so a saved one is answered as it is; a new drawing makes this a new
// worker, which saves the new addresses and drops the old. An address the copy
// does not hold, an older drawing's or one with no fingerprint, goes to the Mac.
//
// The copy belongs to this address. If the Mac's address ever answers with
// another app's page (set up at the same address since), the worker deletes
// the copy and itself, rather than show Job Search where that app should be.

"use strict";

const CACHE = "bs-job-search-1";        // a new name makes phones save afresh, settings and all
const ICONS = "";                       // the drawing's fingerprint: the server writes it in
const HERE = self.location.href.replace(/sw\.js$/, "");
const FILES = ["", "app.js", "style.css"];      // the page's own files, asked again each time
const NAMED = ["manifest.webmanifest", "favicon.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png"];
const V = ICONS ? "?v=" + ICONS : "";
const FIXED = V ? NAMED.map(name => HERE + name + V) : [];   // kept as saved, for good
const OWN = FILES.map(name => HERE + name);
const SHELL = [...OWN, ...NAMED.map(name => HERE + name + V)];
const PAGE = SHELL[0];
const MARK = "<title>BS Job Search";   // in every version of the page (index.html)
const API = HERE + "api/";
const HEALTH = API + "health";          // the page's own truth about the Mac: never from the copy
const SNAPSHOT = API + "snapshot";
const META = HERE + "__copy";           // the copy's own record: the snapshot's tag, when it was saved
// The reads the copy keeps, as core.SNAPSHOT_PATH: the digests, the
// applications, and the profile files. Anything else goes to the Mac.
const KEPT = /^\/api\/(digests(\/\d{4}-\d{2}-\d{2}(\/verdicts)?)?|applications|profile(\/.+)?)$/;
const PROFILE_FILE = /^\/api\/profile\/.+$/;
// Filed documents (resumes, letters, prep sheets, postings), kept apart, only
// when this phone's settings say so, and only those filed in the last DAYS.
const DOCS = "bs-job-search-docs";
const DOC = /^\/api\/applications\/[^/]+\/[^/]+$/;
const DAYS = 30;
const SETTINGS = HERE + "__settings";   // this phone's choices (app.js, This phone in Setup)
const DEFAULTS = { profile: true, documents: false };

const RECENT = 60 * 1000;     // ms since the Mac last answered within which a read asks it first
const ASK = 10 * 1000;        // ms a read waits for a Mac that has answered lately
const COLD = 15 * 1000;       // ms a read with no copy to fall back on waits, time for launchd to start the page
const FAILED = 20 * 1000;     // ms after the Mac failed to answer during which such a read fails at once
const SNAPSHOT_EVERY = 5 * 1000;   // ms between two snapshots, so a run of ticks asks once

let answered = 0;             // when the Mac last answered, ms
let failed = 0;               // when it last did not
let snapshotAt = 0;           // when the snapshot was last asked for
let snapshotting = null;      // the snapshot being taken, if one is
let settings = null;          // this phone's choices, once read
let foreign = false;          // another app answers at this address: the worker steps aside

async function choices() {
  if (settings) return settings;
  try { settings = { ...DEFAULTS, ...(await (await (await caches.open(CACHE)).match(SETTINGS)).json()) }; }
  catch (e) { settings = { ...DEFAULTS }; }
  return settings;
}

// Whether the copy keeps the answer to this read, as this phone's choices stand.
function keeps(p, s) { return KEPT.test(p) && !(PROFILE_FILE.test(p) && !s.profile); }

function path(url) { return new URL(url).pathname; }

// fetch() that gives up after `ms`, and records whether the Mac answered.
// Null when it did not, or answered with an error.
async function ask(url, init, ms) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), ms);
  try {
    const r = await fetch(url, { cache: "no-store", ...init, signal: stop.signal });
    answered = Date.now();
    return r;
  } catch (e) {
    failed = Date.now();
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// A response as the copy keeps it, stamped with when. Rebuilt rather than put
// as it came: Safari will not show a page from a stored response that
// followed a redirect, and the stamp must be a header of its own.
async function keep(cache, url, response) {
  const headers = new Headers(response.headers);
  headers.set("X-Saved-At", new Date().toISOString());
  headers.delete("Content-Length");
  await cache.put(url, new Response(await response.blob(),
    { status: response.status, statusText: response.statusText, headers }));
}

// The copy's answer, marked as the copy's.
function fromCopy(saved) {
  const headers = new Headers(saved.headers);
  headers.set("X-Served-From", "phone");
  return new Response(saved.body, { status: saved.status, statusText: saved.statusText, headers });
}

function unanswered(p = "") {
  const why = PROFILE_FILE.test(p) && settings && !settings.profile
    ? "Your Mac did not answer, and this phone does not keep your profile files: Setup, This phone, says so."
    : "Your Mac did not answer, and this phone has no copy of this.";
  return new Response(JSON.stringify({ detail: why }),
    { status: 504, headers: { "Content-Type": "application/json" } });
}

function tell(message) {
  self.clients.matchAll({ includeUncontrolled: true }).then(all => { for (const c of all) c.postMessage(message); });
}

function same(a, b) {
  const tag = r => r.headers.get("ETag") || r.headers.get("Last-Modified") || "";
  return tag(a) && tag(a) === tag(b);
}

// The Mac's copy of one of the page's files, kept for next time. When the
// file changed since the copy was saved, the page is told: its code is out of
// date and it reloads. When the page is another app's, the copy is deleted
// and that page passed on as it came.
async function refreshShell(cache, url, saved) {
  const fresh = await ask(url, {}, saved ? ASK : COLD);
  if (!fresh || !fresh.ok || foreign) return null;
  if (url === PAGE && !(await fresh.clone().text()).includes(MARK)) {
    foreign = true;
    await forget();
    return fresh;
  }
  if (saved && !same(saved, fresh)) tell({ type: "page", path: path(url) });
  await keep(cache, url, fresh.clone());
  return fresh;
}

// The Mac's answer to one read, kept when the read is one the copy holds.
async function refreshRead(cache, request, url, saved, ms) {
  const fresh = await ask(request, {}, ms);
  if (!fresh) return null;
  if (fresh.ok && keeps(path(url), await choices())) {
    const changed = !saved || (await saved.clone().text()) !== (await fresh.clone().text());
    await keep(cache, url, fresh.clone());
    if (saved && changed) tell({ type: "fresh", path: path(url) });
  }
  return fresh;
}

// Everything the phone keeps for reading, from /api/snapshot, one entry per
// read. Asked with the copy's tag, so an unchanged copy costs a 304. Reads the
// Mac no longer answers (a digest removed) leave the copy.
async function takeSnapshot() {
  if (foreign) return false;
  if (snapshotting) return snapshotting;
  if (Date.now() - snapshotAt < SNAPSHOT_EVERY) return false;
  snapshotAt = Date.now();
  snapshotting = (async () => {
    const cache = await caches.open(CACHE);
    let meta = null;
    try { meta = await (await cache.match(META)).json(); } catch (e) { /* no copy yet */ }
    const headers = meta && meta.etag ? { "If-None-Match": `"${meta.etag}"` } : {};
    const r = await ask(SNAPSHOT, { headers }, ASK);
    if (r && r.status === 304) {          // the copy is current; the documents' drop still runs
      try { await keepDocuments(await (await cache.match(API + "applications")).json(), await choices()); } catch (e) { /* none kept */ }
      return false;
    }
    if (!r || !r.ok) return false;
    const snap = await r.json();
    const s = await choices();
    const at = new Date().toISOString();
    const answers = Object.entries(snap.answers).filter(([p]) => keeps(p, s));
    const kept = new Set(answers.map(([p]) => HERE + p.slice(1)));
    for (const req of await cache.keys()) {
      if (req.url.startsWith(API) && !kept.has(req.url)) await cache.delete(req);
    }
    await keepDocuments(snap.answers["/api/applications"], s);
    for (const [p, value] of answers) {
      const text = typeof value === "string";
      await cache.put(HERE + p.slice(1), new Response(text ? value : JSON.stringify(value),
        { headers: { "Content-Type": text ? "text/plain; charset=utf-8" : "application/json", "X-Saved-At": at } }));
    }
    await cache.put(META, new Response(JSON.stringify({ etag: snap.etag, at }),
      { headers: { "Content-Type": "application/json" } }));
    // The first copy is worth a word on the page; a newer one, a redraw.
    tell(meta ? { type: "fresh", path: "/api/snapshot" } : { type: "copied" });
    return true;
  })().catch(() => false).finally(() => { snapshotting = null; });
  return snapshotting;
}

// The filed documents this phone keeps: when its settings say so, those filed
// in the last DAYS days, each fetched again only when its date or size
// changed. The rest leave the phone, so the drop runs whenever the app opens.
function docUrl(company, name) { return `${API}applications/${encodeURIComponent(company)}/${encodeURIComponent(name)}`; }

async function keepDocuments(listing, s) {
  if (!s.documents || !listing) { await caches.delete(DOCS); return; }
  const since = new Date(Date.now() - DAYS * 86400000).toISOString().slice(0, 10);
  const wanted = new Map();
  for (const f of listing.folders || []) {
    for (const file of f.files || []) {
      if (file.viewable && file.modified >= since) wanted.set(docUrl(f.company, file.name), `${file.modified} ${file.size}`);
    }
  }
  const docs = await caches.open(DOCS);
  for (const req of await docs.keys()) if (!wanted.has(req.url)) await docs.delete(req);
  for (const [url, stamp] of wanted) {
    const have = await docs.match(url);
    if (have && have.headers.get("X-Filed") === stamp) continue;
    const r = await ask(url, {}, COLD);
    if (!r || !r.ok) continue;
    const headers = new Headers(r.headers);
    headers.set("X-Filed", stamp);
    headers.set("X-Saved-At", new Date().toISOString());
    headers.delete("Content-Length");
    await docs.put(url, new Response(await r.blob(), { status: 200, headers }));
  }
}

// This phone's choices change: kept, and the copy taken again whole.
async function choose(next) {
  const cache = await caches.open(CACHE);
  settings = { ...(await choices()), ...next };
  await cache.put(SETTINGS, new Response(JSON.stringify(settings), { headers: { "Content-Type": "application/json" } }));
  await cache.delete(META);
  snapshotAt = 0;
  if (snapshotting) await snapshotting;
  await takeSnapshot();
  tell({ type: "settings", settings });
}

// Forget this phone's copy: everything the worker holds, then the worker itself.
async function forget() {
  for (const name of await caches.keys()) if (name.startsWith("bs-job-search-")) await caches.delete(name);
  settings = null;
  await self.registration.unregister();
  tell({ type: "forgotten" });
}

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    for (const url of SHELL) {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) throw new Error(`${url} answered ${r.status}`);
      await keep(cache, url, r);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("bs-job-search-") && name !== CACHE && name !== DOCS) await caches.delete(name);
    }
    // The page's files this worker does not name, an older drawing's icons
    // among them, leave the copy; the reads and this phone's choices stay.
    const cache = await caches.open(CACHE);
    for (const req of await cache.keys()) {
      if (!req.url.startsWith(API) && req.url !== META && req.url !== SETTINGS && !SHELL.includes(req.url)) {
        await cache.delete(req);
      }
    }
    await self.clients.claim();
    await takeSnapshot();
  })());
});

// The page asks for a fresh snapshot once the Mac answers again, and after
// its own writes.
self.addEventListener("message", event => {
  const m = event.data || {};
  if (foreign) return;
  if (m.type === "refresh") event.waitUntil(takeSnapshot());
  else if (m.type === "settings") event.waitUntil(choose({ profile: !!m.profile, documents: !!m.documents }));
  else if (m.type === "forget") event.waitUntil(forget());
  // What this phone keeps, for the Setup tab to show.
  else if (m.type === "ask") event.waitUntil((async () => {
    let meta = null;
    try { meta = await (await (await caches.open(CACHE)).match(META)).json(); } catch (e) { /* none yet */ }
    const docs = (await caches.has(DOCS)) ? (await (await caches.open(DOCS)).keys()).length : 0;
    event.source.postMessage({ type: "kept", settings: await choices(), savedAt: meta && meta.at, documents: docs, days: DAYS });
  })());
});

async function shell(event, url) {
  const cache = await caches.open(CACHE);
  const saved = await cache.match(url);
  if (saved && FIXED.includes(url)) return saved;      // one drawing for good: nothing to ask
  const fresh = refreshShell(cache, url, saved);       // never rejects
  event.waitUntil(fresh);
  if (url === PAGE) event.waitUntil(fresh.then(r => { if (r) return takeSnapshot(); }));
  if (saved) return saved;
  return (await fresh) || new Response("This phone has no copy of Job Search yet, and the Mac did not answer.",
    { status: 504, headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

async function read(event, request, url) {
  const cache = await caches.open(CACHE);
  const p = path(url);
  // A filed document comes from its own cache, and is refreshed by the snapshot.
  if (DOC.test(p) && (await choices()).documents) {
    const doc = await (await caches.open(DOCS)).match(url);
    if (doc && Date.now() - answered >= RECENT) return fromCopy(doc);
    const fresh = await ask(request, {}, doc ? ASK : COLD);
    return fresh || (doc ? fromCopy(doc) : unanswered());
  }
  const saved = keeps(p, await choices()) ? await cache.match(url) : undefined;
  const recent = Date.now() - answered < RECENT;
  if (saved && !recent) {
    // The Mac has not answered lately: the copy at once, and ask it behind.
    event.waitUntil(refreshRead(cache, request, url, saved, ASK));
    return fromCopy(saved);
  }
  if (!saved && !recent && Date.now() - failed < FAILED) return unanswered(p);
  const fresh = await refreshRead(cache, request, url, saved, saved ? ASK : COLD);
  if (fresh) return fresh;
  return saved ? fromCopy(saved) : unanswered(p);
}

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || foreign) return;        // a write goes to the Mac as it is
  const url = new URL(request.url);
  url.hash = "";
  // An icon or the manifest by its own address, ?v= and all.
  if (SHELL.includes(url.href)) { event.respondWith(shell(event, url.href)); return; }
  url.search = "";                                        // the icon opens ./?from=icon: the same page
  if (OWN.includes(url.href)) { event.respondWith(shell(event, url.href)); return; }
  if (!url.href.startsWith(API) || url.href === HEALTH || url.href === SNAPSHOT) return;
  event.respondWith(read(event, request, url.href));
});
