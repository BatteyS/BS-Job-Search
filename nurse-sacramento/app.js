// The page. No framework and no build step: five tabs over /api, each a
// sidebar and a content pane, apart from Setup's single column; on a phone the
// tabs sit along the bottom and each sidebar folds into a bar (setSide).
// Markdown is rendered with the small renderer at the bottom, which covers
// what the digests and profile files use.
//
// The example demos (ui/build_demo.py) run this same file with no server:
// window.DEMO holds what each route would answer, and demoApi() reads it.

const $ = (sel, el = document) => el.querySelector(sel);
const statusEl = $("#status");
const DEMO = window.DEMO || null;
// Whether this tab is on the Mac itself, or on another device, a phone through
// Tailscale (ui/phone.py): what the page says to do depends on it.
const ON_MAC = ["127.0.0.1", "localhost", "[::1]", "::1"].includes(location.hostname);
// On a phone (this page reached over Tailscale, at a .ts.net address), the SB
// mark also carries this page's address after "#phone=job-search@", the part
// of a link a browser never sends to a server: seanbattey.com keeps it in the
// phone's own storage, and its Launch button opens this page on that phone
// from then on. The link's rel="noreferrer" keeps it from the site's server too.
if (location.protocol === "https:" && location.hostname.endsWith(".ts.net")) {
  const mark = $(".brand-mark-link");
  if (mark) mark.href = "https://seanbattey.com/#phone=job-search@" + encodeURIComponent(location.origin + "/");
}
// Off the Mac, a service worker (sw.js) keeps a copy of this page and of what
// it reads on this device, so the icon opens and shows the digests, the
// applications and the profile files while the Mac cannot be reached. A
// change still needs the Mac. Where a worker cannot run (a plain http:
// address) registering fails, and the Mac answers as before.
// Forget this phone's copy (Setup, This phone) turns it off until asked again.
const NO_COPY_KEY = "bs-job-search.nocopy";
let noCopy = false;
try { noCopy = localStorage.getItem(NO_COPY_KEY) === "1"; } catch (e) { /* storage blocked: keep the copy */ }
const CAN_COPY = !ON_MAC && !DEMO && "serviceWorker" in navigator;
const COPY = CAN_COPY && !noCopy;
if (COPY) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* the Mac answers as before */ });
  // Ask the phone to keep the copy through storage pressure; iOS grants it to a home-screen app.
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
}
const NEEDS_MAC = "Your Mac is not answering, so this cannot be saved. It needs the Mac awake and Tailscale on; this page picks up by itself once it answers.";
const WRITE_WAIT = 12000;   // ms a change waits for the Mac: one that is asleep never answers

// An error stays until the next message. On a phone, where the line is a
// toast over the page (style.css), it goes after eight seconds, or on a tap.
function say(text, isError = false) {
  statusEl.textContent = text;
  statusEl.className = "status" + (isError ? " err" : "");
  const ttl = isError ? (NARROW.matches ? 8000 : 0) : 4000;
  if (ttl) setTimeout(() => { if (statusEl.textContent === text) statusEl.textContent = ""; }, ttl);
}
statusEl.onclick = () => { statusEl.textContent = ""; };

async function api(path, opts = {}) {
  if (DEMO) return demoApi(path, opts);
  // Off the Mac, a change waits a bounded time rather than hanging on a Mac
  // that is asleep, and a short one once the page has seen the Mac away.
  const write = (opts.method || "GET").toUpperCase() !== "GET";
  const ctl = write && !ON_MAC && window.AbortController ? new AbortController() : null;
  const timer = ctl && setTimeout(() => ctl.abort(), fromPhone ? 3000 : WRITE_WAIT);
  let r;
  try { r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, ...(ctl ? { signal: ctl.signal } : {}) }); }
  catch (e) { throw new Error(write && !ON_MAC ? NEEDS_MAC : e.message); }
  finally { if (timer) clearTimeout(timer); }
  noteServed(r);
  if (!r.ok) {
    let msg = r.statusText, current = null;
    try {
      const detail = (await r.json()).detail;
      // A 409 conflict says what is there now, beside its message.
      if (detail && typeof detail === "object") { msg = detail.message || msg; current = detail.current || null; }
      else msg = detail || msg;
    } catch (_) { /* not json */ }
    throw Object.assign(new Error(msg), { status: r.status, current });
  }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "html") node.innerHTML = v;
    // null or false leaves the attribute off: setAttribute("disabled", null)
    // would still disable the element.
    else if (v != null && v !== false) node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

// ------------------------------------------------------------------ tabs

for (const b of document.querySelectorAll("nav button")) {
  b.addEventListener("click", () => showTab(b.dataset.tab));
}
const loaded = {};
function showTab(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("active", b.dataset.tab === name);
  for (const t of document.querySelectorAll(".tab")) t.classList.toggle("active", t.id === "tab-" + name);
  // Setup checks again each time it is shown: setup runs elsewhere, in Runs.
  if (name === "setup") loadSetup();
  else if (!loaded[name]) { loaded[name] = true; ({ digests: loadDigests, applications: loadApplications, runs: loadRuns, profile: loadProfile })[name](); }
  location.hash = name;
  if (NARROW.matches) window.scrollTo(0, 0);
}

// ------------------------------------------------------------- sidebars
// On a phone (style.css, the narrow breakpoint) each tab's sidebar folds into
// one bar that names what is open: the digest's date, the company, the file.
// A tap unfolds the list; picking from it folds it again and brings the
// content back to the top of the screen. Wider, the bar is not shown and the
// sidebar is always there, so the fold state changes nothing.

const NARROW = window.matchMedia ? matchMedia("(max-width: 700px)") : { matches: false };

function setSide(tab, open) {
  const sec = $("#tab-" + tab);
  sec.classList.toggle("side-open", open);
  sec.querySelector(".side-toggle").setAttribute("aria-expanded", String(open));
}

// What was picked: name it on the bar, and on a phone fold the list.
function pickSide(tab, ...label) {
  const sec = $("#tab-" + tab);
  if (label.length) sec.querySelector(".side-label").replaceChildren(...label);
  if (!NARROW.matches) return;
  setSide(tab, false);
  const top = sec.getBoundingClientRect().top;
  if (top < 0) window.scrollBy(0, top);
}

for (const t of document.querySelectorAll(".side-toggle")) {
  const tab = t.closest(".tab").id.slice(4);
  setSide(tab, true);
  t.onclick = () => setSide(tab, t.getAttribute("aria-expanded") !== "true");
}

// While a field has the keyboard up, the tab bar hides (style.css).
const TYPED = "input:not([type=checkbox]):not([type=radio]), textarea";
document.addEventListener("focusin", ev => { if (ev.target.matches && ev.target.matches(TYPED)) document.body.classList.add("typing"); });
document.addEventListener("focusout", () => document.body.classList.remove("typing"));

// --------------------------------------------------------------- digests

let currentDigest = null;

async function loadDigests() {
  const list = $("#digest-list");
  list.replaceChildren();
  let digests;
  try { digests = await api("/api/digests"); } catch (e) { say(e.message, true); return; }
  if (!digests.length) { list.append(el("p", { class: "muted" }, "No digests yet. A scan writes one: Job scan, in the Runs tab.")); return; }
  for (const d of digests) {
    list.append(el("button", { class: "item", "data-date": d.date, onclick: () => openDigest(d.date) }, d.date, el("small", {}, digestCounts(d))));
  }
  if (!currentDigest) openDigest(digests[0].date);
}

function digestCounts(d) {
  return `${d.entries} roles · ${d.apply} apply · ${d.skip} skip` + (d.unmarked ? ` · ${d.unmarked} unmarked` : "") + (d.conflicts ? ` · ${d.conflicts} to settle` : "");
}

function refreshDigestCounts(d) {
  const b = $(`#digest-list [data-date="${d.date}"] small`);
  if (b) b.textContent = digestCounts(d);
  if (currentDigest === d.date) $("#tab-digests .side-label").replaceChildren(d.date, " ", el("small", {}, digestCounts(d)));
}

async function openDigest(date) {
  currentDigest = date;
  for (const b of document.querySelectorAll("#digest-list .item")) b.classList.toggle("active", b.dataset.date === date);
  const counts = $(`#digest-list [data-date="${date}"] small`);
  pickSide("digests", date, " ", el("small", {}, counts ? counts.textContent : ""));
  const view = $("#digest-view");
  view.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  let d;
  try { d = await api("/api/digests/" + date); } catch (e) { view.replaceChildren(el("p", { class: "muted" }, e.message)); return; }
  // Ticks made on this phone that the Mac has not taken yet show as made.
  for (const o of outbox) {
    const m = o.kind === "mark" && o.path.match(/^\/api\/digests\/([^/]+)\/entries\/(\d+)$/);
    const en = m && m[1] === date && d.entries.find(x => x.n === Number(m[2]));
    if (en) localMark(en, o.body);
  }
  if (outbox.length) refreshDigestCounts(markCounts(d));

  const verdictsOut = el("div");
  const toolbar = el("div", { class: "toolbar" },
    el("button", { class: "action", onclick: () => showVerdicts(date, verdictsOut) }, "Verdicts for feedback.md"),
    el("button", { class: "action", onclick: () => startRun("applies", { date }, true) }, "What is marked"),
    el("button", { class: "action", onclick: () => startRun("fetch", { date }, true) }, "Fetch postings"),
  );
  view.replaceChildren(toolbar, verdictsOut, el("div", { class: "md", html: markdown(d.preamble) }));
  for (const e of d.entries) view.append(entryCard(date, e));
}

function entryCard(date, e) {
  const card = el("div", { class: "entry" });
  const state = () => { card.classList.toggle("applied", e.marked_apply && !e.marked_skip); card.classList.toggle("skipped", e.marked_skip && !e.marked_apply); };
  state();

  const meta = [e.metro, e.comp].filter(Boolean).join(" · ");
  card.append(
    el("h3", {}, el("span", { class: "score" }, e.score ?? "–"), `${e.n}. ${e.company} — ${e.title}`),
    el("div", { class: "meta" }, meta),
  );

  const apply = el("input", { type: "checkbox" }); apply.checked = e.marked_apply;
  const skip = el("input", { type: "checkbox" }); skip.checked = e.marked_skip;
  const letter = el("input", { type: "checkbox" }); letter.checked = e.marked_letter;
  const reason = el("input", { type: "text", placeholder: "skip — reason (say why: it teaches the scorer)", value: e.skip_reason || "" });

  // Each change says what this card showed in the boxes it changes, and which
  // role it is for, so one made against a digest changed since (by a scan, a
  // skill, or another tab) is refused rather than written over it.
  const shown = { apply: "marked_apply", skip: "marked_skip", letter: "marked_letter", skip_reason: "skip_reason" };
  const path = `/api/digests/${date}/entries/${e.n}`;
  const wait = el("span", { class: "chip warn", hidden: "" });
  const waiting = () => {
    const q = outbox.find(o => o.kind === "mark" && o.path === path);
    wait.hidden = !q;
    if (q) { wait.textContent = q.conflict ? "to settle: see the header" : "waiting for your Mac"; wait.className = "chip " + (q.conflict ? "bad" : "warn"); }
    card.classList.toggle("waiting", !!q);
  };
  async function save(marks) {
    const expect = Object.fromEntries(Object.keys(shown).map(k => [k, k === "skip_reason" ? e.skip_reason || "" : !!e[shown[k]]]));
    const edit = { id: editId(), kind: "mark", at: new Date().toISOString(), path, label: `${e.company} — ${e.title}: ${markSaid(marks)}`,
                   body: { ...marks, expect, entry: { company: e.company, title: e.title } } };
    const made = () => { Object.assign(e, { marked_apply: apply.checked, marked_skip: skip.checked, marked_letter: letter.checked, skip_reason: reason.value }); state(); };
    try {
      const counts = await send(edit);
      made(); refreshDigestCounts(counts); waiting(); say(DEMO ? "Ticked on this page only: the demo saves nothing." : `Saved #${e.n}`);
    } catch (err) {
      // Queued on this phone: the tick shows as made, and goes when the Mac answers.
      if (err.queued) { made(); waiting(); say(err.message); return; }
      say(err.message, true);
      if (err.status === 409 && currentDigest === date) openDigest(date).then(() => say(err.message, true));
      // Not saved at all: the boxes go back to what the file holds.
      else if (!err.status) { apply.checked = e.marked_apply; skip.checked = e.marked_skip; letter.checked = e.marked_letter; reason.value = e.skip_reason || ""; }
    }
  }
  apply.onchange = () => save({ apply: apply.checked });
  skip.onchange = () => save({ skip: skip.checked, skip_reason: reason.value });
  letter.onchange = () => save({ letter: letter.checked });
  let lastReason = reason.value;
  const saveReason = () => { if (reason.value !== lastReason) { lastReason = reason.value; save({ skip_reason: reason.value, ...(reason.value && !skip.checked ? { skip: (skip.checked = true) } : {}) }); } };
  reason.onblur = saveReason;
  reason.onkeydown = ev => { if (ev.key === "Enter") reason.blur(); };

  waiting();
  card.append(el("div", { class: "marks" },
    el("label", {}, apply, "apply"),
    el("label", {}, skip, "skip"),
    reason,
    el("label", {}, letter, "cover letter"),
    wait,
  ));

  const chips = el("div", {});
  if (e.status) chips.append(el("span", { class: "chip" + (ANSWERED.has(e.status) ? " ok" : ""), title: "Where the application stands, in the Applications tab" }, `${e.status} · ${e.status_since}`));
  else if (e.already_built) chips.append(el("span", { class: "chip ok" }, "resume filed"));
  if (e.letter_built) chips.append(el("span", { class: "chip ok" }, "letter filed"));
  if (e.suggested_variant) chips.append(el("span", { class: "chip" }, "resume: " + e.suggested_variant));
  if (e.folder_note) chips.append(el("span", { class: "chip warn" }, e.folder_note));
  if (e.marked_apply && e.marked_skip) chips.append(el("span", { class: "chip bad" }, "apply and skip both ticked"));
  if (e.marked_letter && !e.marked_apply) chips.append(el("span", { class: "chip bad" }, "letter without apply"));
  if (chips.childElementCount) card.append(chips);

  card.append(el("div", { class: "body md", html: markdown(e.body) }));
  return card;
}

async function showVerdicts(date, out) {
  out.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  try {
    const v = await api(`/api/digests/${date}/verdicts`);
    const pre = el("pre", { class: "text" }, v.section);
    const append = el("button", { class: "action primary", onclick: async () => {
      append.disabled = true;
      try { const r = await api(`/api/digests/${date}/verdicts/append`, { method: "POST" }); say(`Appended to ${r.appended_to}`); out.replaceChildren(el("p", { class: "muted" }, `Appended to ${r.appended_to}.`)); }
      catch (e) { say(e.message, true); append.disabled = false; }
    } }, "Append to feedback.md");
    const settle = v.settle.length ? el("div", { class: "md", html: "<p><b>Settle first:</b></p><ul>" + v.settle.map(s => `<li>${esc(s)}</li>`).join("") + "</ul>" }) : null;
    if (settle) append.disabled = true;
    out.replaceChildren(el("div", { class: "run" }, el("div", { class: "head" }, el("b", {}, "Verdicts, as a feedback.md section"), append, el("button", { class: "action", onclick: () => out.replaceChildren() }, "Close")), settle, pre));
  } catch (e) { out.replaceChildren(el("p", { class: "muted" }, e.message)); }
}

// ---------------------------------------------------------- applications
// What was filed under Applications/, and where each application stands. A
// status, its date and a note are saved to profile/applications.yaml, which git
// tracks, so another machine shows them though Applications/ stays on the one
// that filed it; the next scan reads what came of each. The table of every
// application and each employer's page are built from the same rows.

let apps = null;          // what /api/applications answers
let appOpen = "all";      // the table of every application, or one folder's name

// The statuses that mean a person answered with interest.
const ANSWERED = new Set(["heard back", "interviewing", "offer", "accepted"]);

async function loadApplications() {
  try { apps = await api("/api/applications"); } catch (e) { say(e.message, true); return; }
  // Changes made on this phone that the Mac has not taken yet show as made.
  for (const o of outbox) if (o.kind === "status" && !o.conflict) localStatus(apps, o.body);
  if (appOpen !== "all" && apps.folders.some(f => f.company === appOpen)) openApplication(appOpen);
  else openTracker();
}

function appRows() { return apps.folders.filter(f => f.employer).flatMap(f => f.roles); }

// "3 applied · 1 heard back · 4 no status", in the statuses' own order.
function appCounts(rows) {
  const n = {};
  for (const r of rows) { const k = r.status || "no status"; n[k] = (n[k] || 0) + 1; }
  return [...apps.statuses, "no status"].filter(k => n[k]).map(k => `${n[k]} ${k}`).join(" · ") || "nothing yet";
}

function folderLine(f) {
  const files = f.on_disk ? `${f.files.length} file${f.files.length === 1 ? "" : "s"}` : "files not on this machine";
  if (!f.employer) return files;
  const st = apps.statuses.filter(s => f.roles.some(r => r.status === s));
  return [st.length ? st.join(" · ") : "no status", files].join(" · ");
}

function renderAppList() {
  const list = $("#app-list");
  const item = (f, label) => el("button", { class: "item", "data-app": f.company, onclick: () => openApplication(f.company) }, label || f.company, el("small", {}, folderLine(f)));
  const here = apps.folders.filter(f => f.employer && f.on_disk), away = apps.folders.filter(f => f.employer && !f.on_disk), other = apps.folders.filter(f => !f.employer);
  list.replaceChildren(el("button", { class: "item", "data-app": "all", onclick: () => openTracker() }, "All applications", el("small", {}, appCounts(appRows()))));
  if (!apps.folders.length) list.append(el("p", { class: "muted" }, "Nothing filed under Applications/ yet."));
  for (const f of here) list.append(item(f));
  if (away.length) { list.append(el("h3", {}, "Not on this machine")); for (const f of away) list.append(item(f)); }
  if (other.length) { list.append(el("h3", {}, "Not employers")); for (const f of other) list.append(item(f, f.company.replace(/^_[^/]*\//, ""))); }
  for (const b of list.querySelectorAll(".item")) b.classList.toggle("active", b.dataset.app === appOpen);
}

function appProblems() {
  return [apps.problem, ...(apps.problems || [])].filter(Boolean).map(p => el("p", { class: "banner bad" }, p));
}

function openTracker() {
  appOpen = "all";
  renderAppList();
  pickSide("applications", "All applications", " ", el("small", {}, appCounts(appRows())));
  // The latest change first, then what has no status yet. A change does not
  // re-sort the table, so a row stays where it was while it is being edited.
  const rows = appRows().slice().sort((a, b) => (b.since || "").localeCompare(a.since || "")
    || a.company.localeCompare(b.company) || a.role.localeCompare(b.role));
  $("#app-view").replaceChildren(
    el("h2", {}, "Applications"),
    el("p", { class: "muted small" }, `Where each one stands. Pick a status as it changes: it is dated today unless you set the date back. Everything is saved to ${apps.file}, which git tracks, so it reaches your other machine, and the next scan reads what came of each.`),
    ...appProblems(),
    el("p", { id: "app-counts", class: "small" }, appCounts(rows)),
    rows.length ? el("div", { class: "tracker" }, ...rows.map(r => statusRow(r, true)))
      : el("p", { class: "muted" }, "Nothing yet. A tailored resume shows up here: mark it applied once you send it."));
}

function openApplication(company) {
  const f = apps.folders.find(x => x.company === company);
  if (!f) { openTracker(); return; }
  appOpen = company;
  renderAppList();
  pickSide("applications", f.company, " ", el("small", {}, folderLine(f)));
  const viewer = el("div");
  const files = el("ul", { class: "files" });
  for (const file of f.files) {
    const url = fileUrl(f.company, file.name);
    const link = file.viewable
      ? el("a", { href: "#", onclick: ev => { ev.preventDefault(); showFile(viewer, url, file.name); } }, file.name)
      : el("span", { class: "muted" }, file.name);
    files.append(el("li", {}, link, el("small", {}, `${file.modified} · ${fmtSize(file.size)}`)));
  }
  $("#app-view").replaceChildren(el("h2", {}, f.company),
    ...(f.employer ? [...appProblems(), el("div", { class: "tracker" }, ...f.roles.map(r => statusRow(r, false)))] : []),
    f.on_disk ? files : el("p", { class: "muted" }, `Its files are not on this machine: Applications/ stays on the machine that filed it, and ${apps.file} goes everywhere.`),
    viewer);
  const first = f.files.find(x => x.viewable && x.name.endsWith(".pdf")) || f.files.find(x => x.viewable);
  if (first) showFile(viewer, fileUrl(f.company, first.name), first.name);
}

// One application: its status, the date it got there, Undo for the last
// change, and a note. Each change is saved as it is made, the way a digest's
// boxes are, and the row redraws from what the server answers.
function statusRow(r, withCompany) {
  const row = el("div", { class: "app-row" });

  // Each change says the last line and the note this row showed, so one made
  // against a tracker changed since is refused rather than written over it.
  async function save(change) {
    const h = r.history, last = h.length ? h[h.length - 1] : null, before = h.length > 1 ? h[h.length - 2] : null;
    const seen = { expect_last: last ? `${last.date} ${last.status}` : "", ...("note" in change ? { expect_note: r.note || "" } : {}) };
    const edit = { id: editId(), kind: "status", at: new Date().toISOString(), path: "/api/applications/status",
                   label: `${r.company} — ${r.role || "the employer as a whole"}: ${statusSaid(change)}`,
                   body: { company: r.company, role: r.role, ...change, ...seen },
                   // The line an undo leaves last: an undo sent again, after its answer was lost, is then done.
                   before: before ? `${before.date} ${before.status}` : "" };
    const drawn = () => {
      const next = appRows().find(x => x.company === r.company && x.role === r.role);
      if (next) { r = next; draw(); } else row.remove();
      if (appOpen !== "all" && !apps.folders.some(f => f.company === appOpen)) { openTracker(); return; }
      renderAppList();
      const counts = $("#app-counts");
      if (counts) counts.textContent = appCounts(appRows());
      const bar = $("#tab-applications .side-label small");
      if (bar) bar.textContent = appOpen === "all" ? appCounts(appRows()) : folderLine(apps.folders.find(f => f.company === appOpen));
    };
    try {
      apps = await send(edit);
      drawn();
      say(DEMO ? "Changed on this page only: the demo saves nothing." : `Saved to ${apps.file}`);
    } catch (e) {
      // Queued on this phone: the change shows as made, and goes when the Mac answers.
      if (e.queued) { localStatus(apps, edit.body); drawn(); say(e.message); return; }
      say(e.message, true);
      // Changed elsewhere since: show what is there now, and say so again.
      if (e.status === 409 && e.current) { await loadApplications(); say(e.message, true); return; }
      if (!("note" in change)) draw();   // a refused note stays as typed, to fix
    }
  }

  function draw() {
    const locked = !!(r.problem || apps.problem);
    const who = el("div", { class: "who" },
      withCompany ? el("a", { href: "#", onclick: ev => { ev.preventDefault(); openApplication(r.company); } }, r.company) : null,
      withCompany ? " — " : null,
      el("span", { class: r.role ? "role" : "role muted" }, r.role || "the employer as a whole"));
    const chips = el("span", { class: "chips" });
    if (r.digest) chips.append(el("span", { class: "chip", title: `Entry #${r.digest.n} in the ${r.digest.date} digest` }, `scored ${r.digest.score ?? "?"} · ${r.digest.date}`));
    if (r.waiting) chips.append(el("span", { class: "chip warn", title: "Mark it no response once you stop expecting an answer" }, `no word in ${r.waiting} days`));
    if (r.role && !r.filed) chips.append(el("span", { class: "chip" }, "files not on this machine"));
    if (r.problem) chips.append(el("span", { class: "chip bad", title: r.problem }, `fix by hand in ${apps.file}`));
    const queued = outbox.filter(o => o.kind === "status" && o.body.company === r.company && (o.body.role || "") === (r.role || ""));
    if (queued.length) chips.append(el("span", { class: "chip " + (queued.some(o => o.conflict) ? "bad" : "warn") },
      queued.some(o => o.conflict) ? "to settle: see the header" : "waiting for your Mac"));
    if (chips.childElementCount) who.append(chips);

    // Only the moves the tracker takes: a step further, or an ending. Undo
    // fixes a mistake without losing the dates in between.
    const select = el("select", { "aria-label": "Status", disabled: locked || null });
    if (!r.status) select.append(el("option", { value: "" }, "no status"));
    const offered = new Set([r.status, ...(r.moves || [])]);
    for (const s of apps.statuses) if (offered.has(s)) select.append(el("option", { value: s }, s));
    select.value = r.status || "";
    select.title = r.status ? apps.meaning[r.status] : "Pick one once you send it";
    select.onchange = () => { if (select.value) save({ status: select.value }); };

    const before = r.history.length > 1 ? r.history[r.history.length - 2].date : null;
    const date = el("input", { type: "date", "aria-label": "When it got there", title: "When it got there", value: r.since || "", max: apps.today, min: before, disabled: (locked || !r.status) || null });
    date.onchange = () => { if (date.value && date.value !== r.since) save({ date: date.value }); };

    const last = r.history[r.history.length - 1];
    const undo = last ? el("button", { class: "action small", disabled: locked || null, title: `Remove the last change: ${last.status}, ${last.date}`, onclick: () => save({ undo: true }) }, "Undo") : null;

    const note = el("input", { type: "text", class: "note", "aria-label": "Note", maxlength: "500", disabled: locked || null, value: r.note || "", placeholder: "note: what they said, or why it ended (it teaches the scan)" });
    note.onblur = () => { if (note.value.trim() !== (r.note || "")) save({ note: note.value }); };
    note.onkeydown = ev => { if (ev.key === "Enter") note.blur(); };

    const history = r.history.length ? el("div", { class: "history" }, r.history.map(h => `${h.status} ${h.date}`).join(" → ")) : null;
    row.classList.toggle("ended", !!r.ended);
    row.classList.toggle("answered", ANSWERED.has(r.status));
    row.replaceChildren(...[who, el("div", { class: "set" }, select, date, undo), note, history].filter(Boolean));
  }

  draw();
  return row;
}

// A filed document: from the server, or in a demo from the copies beside the page.
function fileUrl(company, name) {
  if (DEMO) return "files/" + [...company.split("/"), name].map(encodeURIComponent).join("/");
  return `/api/applications/${encodeURIComponent(company)}/${encodeURIComponent(name)}`;
}

async function showFile(viewer, url, name) {
  // A phone shows only a framed PDF's first page, so a link opens all of it,
  // and where the device can share files, Share hands the whole PDF to its
  // share sheet: Quick Look, Save to Files, Print, Mail. The file is fetched
  // first, so the tap itself shares at once, as iOS requires.
  if (name.toLowerCase().endsWith(".pdf")) {
    const share = el("button", { class: "action small", hidden: "" }, "Share");
    viewer.replaceChildren(el("p", { class: "small toolbar" }, el("a", { href: url, target: "_blank", rel: "noopener" }, "Open the whole PDF"), share), el("iframe", { class: "pdf", src: url }));
    if (!DEMO && navigator.canShare && window.File) {
      fetch(url).then(r => r.ok ? r.blob() : Promise.reject(new Error(r.statusText))).then(blob => {
        const file = new File([blob], name, { type: "application/pdf" });
        if (!navigator.canShare({ files: [file] })) return;
        share.hidden = false;
        share.onclick = () => navigator.share({ files: [file], title: name }).catch(e => { if (e.name !== "AbortError") say(e.message, true); });
      }).catch(() => { /* no Share: the link and the frame stay */ });
    }
    return;
  }
  viewer.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  try {
    const text = await api(url);
    viewer.replaceChildren(name.endsWith(".md") ? el("div", { class: "md", html: markdown(text) }) : el("pre", { class: "text" }, text));
  } catch (e) { viewer.replaceChildren(el("p", { class: "muted" }, e.message)); }
}

function fmtSize(n) { return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`; }

// ------------------------------------------------------------------ runs
// Two kinds share the tab: scripts (lines of output) and skills, which run
// through the user's own Claude Code and render as a conversation with cards
// for every approval and question. Both stream over /api/runs/<id>/stream.

let activeClaude = null;   // the skill run still going, if any

async function loadRuns() {
  const side = $("#run-commands");
  side.replaceChildren();
  let cmds, status = { available: false, reason: "" }, skills = [];
  try { cmds = await api("/api/commands"); }
  catch (e) { side.replaceChildren(el("p", { class: "banner" }, fromPhone ? "Runs need your Mac, and it is not answering." : e.message)); return; }
  try { status = await api("/api/claude/status"); if (status.available) skills = await api("/api/skills"); } catch (e) { status = { available: false, reason: e.message }; }

  side.append(el("h3", {}, "Skills"));
  if (status.available) {
    side.append(el("p", { class: "muted small" }, DEMO ? DEMO.runsNote : `Claude Code ${status.version || ""} (${status.how})`));
    side.append(pickRow());
    for (const s of skills) side.append(skillButton(s));
  } else {
    side.append(el("p", { class: "muted small" }, "Not available: " + status.reason));
  }
  side.append(el("h3", {}, "Scripts"));
  for (const c of cmds) {
    side.append(el("button", { class: "item", onclick: () => startRun(c.name, c.needs_date ? { date: currentDigest } : {}) }, c.label, el("small", {}, c.about + (c.needs_date ? " (for the digest open in Digests)" : ""))));
  }
  if (status.available) await loadPastRuns(side);

  let old = [];
  try { old = await api("/api/runs"); } catch (e) { /* the Mac is away: nothing to attach */ }
  for (const r of old) attachRun(r, false);
  // Opened with a run still going, as a phone checking on one: show the run.
  if (old.some(r => ACTIVE.includes(r.status))) pickSide("runs");
  refreshSkillButtons();
}

function skillButton(s) {
  const btn = el("button", { class: "item skill", "data-skill": s.name }, s.label, el("small", {}, s.about + (s.needs === "date" ? " (the digest open in Digests)" : "")), routeLine(s.route));
  btn.route = s.route;
  btn.onclick = () => {
    if (s.needs === "application") { pickApplication(s, btn); return; }
    if (s.needs !== "text") { startSkill(s.name, s.needs === "date" ? { date: currentDigest } : {}); return; }
    const box = el("textarea", { placeholder: "Paste the posting's URL, or the posting itself", rows: 4 });
    const go = el("button", { class: "action primary", onclick: () => { if (box.value.trim()) { startSkill(s.name, { text: box.value.trim() }); form.remove(); } } }, "Start");
    const form = el("div", { class: "skill-form" }, box, el("div", { class: "toolbar" }, go, el("button", { class: "action", onclick: () => form.remove() }, "Cancel")));
    btn.after(form);
    box.focus();
  };
  return btn;
}

// A skill for one application (Interview prep) picks from the postings filed
// under Applications/, newest first: every resume the skills build saves one.
const POSTING = " - posting.txt";
async function pickApplication(s, btn) {
  if (btn.nextElementSibling && btn.nextElementSibling.classList.contains("skill-form")) return;
  let apps = [];
  try { apps = (await api("/api/applications")).folders; } catch (e) { say(e.message, true); return; }
  const filed = apps.filter(a => a.employer).flatMap(a => a.files.filter(f => f.name.endsWith(POSTING))
    .map(f => ({ company: a.company, title: f.name.slice(0, -POSTING.length), modified: f.modified })))
    .sort((a, b) => b.modified.localeCompare(a.modified) || a.company.localeCompare(b.company));
  if (!filed.length) { say("No posting is filed under Applications/ yet. Tailoring a resume files one.", true); return; }
  const pick = el("select", { "aria-label": "Application" }, ...filed.map((a, i) => el("option", { value: String(i) }, `${a.company} · ${a.title}`)));
  const go = el("button", { class: "action primary", onclick: () => { const a = filed[Number(pick.value)]; form.remove(); startSkill(s.name, { company: a.company, title: a.title }); } }, "Start");
  const form = el("div", { class: "skill-form" }, pick, el("div", { class: "toolbar" }, go, el("button", { class: "action", onclick: () => form.remove() }, "Cancel")));
  btn.after(form);
  pick.focus();
}

// One skill works at a time. One that has finished its turn and waits for a
// reply (idle) holds nothing: starting another skill ends it, and Past runs
// picks it up again.
function refreshSkillButtons() {
  const working = !!activeClaude && WORKING.includes(activeClaude.status);
  for (const b of document.querySelectorAll("#run-commands .skill")) b.disabled = working;
  const banner = $("#run-active");
  if (activeClaude) {
    const text = working ? `${activeClaude.name} is ${activeClaude.status}. One skill runs at a time.`
      : `${activeClaude.name} is waiting for your reply. Starting another skill ends it; Past runs can pick it up again.`;
    if (banner) banner.textContent = text; else $("#run-commands").prepend(el("p", { id: "run-active", class: "banner" }, text));
  } else if (banner) banner.remove();
}

async function loadPastRuns(side) {
  let past = [];
  try { past = await api("/api/claude/runs"); } catch (e) { return; }
  const old = past.filter(p => p.session_id && !["starting", "running", "waiting", "idle"].includes(p.status) || !document.querySelector(`[data-run="${p.id}"]`));
  if (!old.length) return;
  side.append(el("h3", {}, "Past runs"));
  for (const p of old.slice(0, 8)) {
    const when = new Date(p.started * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const btn = el("button", { class: "item" }, `${p.skill} · ${p.status}`, el("small", {}, [when, p.route, p.cost ? `≈$${p.cost.toFixed(2)}` : "", p.prompt].filter(Boolean).join(" · ")));
    btn.onclick = () => {
      const box = el("textarea", { placeholder: "What next? This continues the same conversation.", rows: 3 });
      const go = el("button", { class: "action primary", onclick: async () => {
        if (!box.value.trim()) return;
        try { const run = await api("/api/claude/resume", { method: "POST", body: JSON.stringify({ session_id: p.session_id, text: box.value.trim(), ...activePick() }) }); form.remove(); attachRun(run, true); pickSide("runs"); }
        catch (e) { say(e.message, true); }
      } }, "Resume");
      const form = el("div", { class: "skill-form" }, box, el("div", { class: "toolbar" }, go, el("button", { class: "action", onclick: () => form.remove() }, "Cancel")));
      btn.after(form); box.focus();
    };
    side.append(btn);
  }
}

async function startSkill(name, params) {
  if (params && "date" in params && !params.date) delete params.date;
  let run;
  try { run = await api("/api/skills/" + name, { method: "POST", body: JSON.stringify({ ...(params || {}), ...activePick() }) }); }
  catch (e) { say(e.message, true); return; }
  loaded.runs = true;
  attachRun(run, true);
  showTab("runs");
  pickSide("runs");
}

async function startRun(name, params, switchTab = false) {
  if (params && "date" in params && !params.date) { say("Open a digest first", true); return; }
  let run;
  try { run = await api("/api/runs/" + name, { method: "POST", body: JSON.stringify(params || {}) }); }
  catch (e) { say(e.message, true); return; }
  loaded.runs = true;
  attachRun(run, true);
  if (switchTab) showTab("runs");
  pickSide("runs");
}

function attachRun(run, live) {
  if (document.querySelector(`[data-run="${run.id}"]`)) return;
  if (run.kind === "claude") { attachClaudeRun(run, live); return; }
  const view = $("#run-view");
  if (view.firstElementChild && view.firstElementChild.classList.contains("muted")) view.replaceChildren();
  const st = el("span", { class: "st " + run.status }, run.status);
  const pre = el("pre", { class: "out" });
  const when = new Date(run.started * 1000).toLocaleTimeString();
  view.prepend(el("div", { class: "run", "data-run": run.id }, el("div", { class: "head" }, el("b", {}, run.name), el("span", { class: "muted" }, when), st), pre));
  if (!live) {
    api("/api/runs/" + run.id).then(r => { pre.textContent = r.output.join("\n"); });
    return;
  }
  // Live output. A phone drops the stream when it puts the page in the
  // background, and a Mac can sleep or change networks: then catch up from the
  // run itself, and follow it again from there while it is still going, at
  // once when the page is shown again.
  let es = null, seen = 0, ended = false, retry = null;
  const end = status => {
    ended = true; clearTimeout(retry);
    st.textContent = status; st.className = "st " + status;
    document.removeEventListener("visibilitychange", wake);
    if (loaded.digests && currentDigest) openDigest(currentDigest);
  };
  const follow = () => {
    if (ended || es) return;
    es = new EventSource(`/api/runs/${run.id}/stream?start=${seen}`);
    es.onmessage = ev => {
      seen = ev.lastEventId !== "" ? Number(ev.lastEventId) + 1 : seen + 1;
      pre.textContent += (pre.textContent ? "\n" : "") + ev.data; pre.scrollTop = pre.scrollHeight;
    };
    es.addEventListener("done", ev => { es.close(); es = null; end(ev.data); });
    es.onerror = () => { es.close(); es = null; catchUp(1500); };
  };
  const catchUp = delay => {
    clearTimeout(retry);
    retry = setTimeout(() => api("/api/runs/" + run.id).then(r => {
      pre.textContent = r.output.join("\n"); pre.scrollTop = pre.scrollHeight; seen = r.output.length;
      if (r.status === "running") follow(); else end(r.status);
    }).catch(e => {
      // A server that no longer knows the run has restarted, and the page
      // reloads (heartbeat); anything else is the Mac not answering yet.
      if (e.status === 404) { ended = true; document.removeEventListener("visibilitychange", wake); }
      else catchUp(3000);
    }), delay);
  };
  const wake = () => { if (!document.hidden && !ended && !es) catchUp(0); };
  document.addEventListener("visibilitychange", wake);
  follow();
}

// ------------------------------------------------------- a skill's run

const ACTIVE = ["starting", "running", "waiting", "idle"];
const WORKING = ["starting", "running", "waiting"];   // idle: the turn is over
// A phone's keyboard has Return and no Shift+Return, so there Return is a new
// line and the Send button sends; on a Mac, Return sends, as in a chat.
const TOUCH = !!(window.matchMedia && matchMedia("(pointer: coarse)").matches);

async function attachClaudeRun(run, live) {
  const view = $("#run-view");
  if (view.firstElementChild && view.firstElementChild.classList.contains("muted")) view.replaceChildren();
  const st = el("span", { class: "st " + run.status }, run.status);
  const stop = el("button", { class: "action small" }, "Stop");
  const transcript = el("div", { class: "chat" });
  const cardArea = el("div");
  const reply = el("textarea", { class: "reply", rows: 2, enterkeyhint: TOUCH ? "enter" : "send",
    placeholder: TOUCH ? "Reply… (tap Send to send it)" : "Reply… (Enter sends, Shift+Enter for a new line)" });
  const send = el("button", { class: "action primary" }, "Send");
  const replyBox = el("div", { class: "replybox", hidden: "" }, reply, send);
  const when = new Date(run.started * 1000).toLocaleTimeString();
  const routed = run.route && run.route.label ? el("span", { class: "chip", title: run.route.why || "" }, run.route.label) : null;
  const filedBox = el("div", { class: "filed" });
  const panel = el("div", { class: "run claude", "data-run": run.id },
    el("div", { class: "head" }, el("b", {}, run.name), routed, el("span", { class: "muted" }, when), st, stop),
    transcript, filedBox, cardArea, replyBox);
  view.prepend(panel);

  // What this run filed under Applications/: a resume, a letter, a prep sheet,
  // each opened here. From its start to its last change, or to now while it is
  // still going.
  const showFiled = async until => {
    let files = [];
    try { files = await api(`/api/filed?since=${run.started - 1}` + (until ? `&until=${until + 1}` : "")); } catch (e) { return; }
    const viewer = el("div");
    filedBox.replaceChildren(...(files.length ? [el("p", { class: "small" }, el("b", {}, "Filed: "),
      ...files.flatMap((f, i) => [i ? " · " : "", f.viewable
        ? el("a", { href: "#", onclick: ev => { ev.preventDefault(); showFile(viewer, fileUrl(f.company, f.name), f.name); } }, `${f.company}/${f.name}`)
        : `${f.company}/${f.name}`])), viewer] : []));
  };

  const state = { status: run.status, tools: {}, seen: 0, replayed: false };
  const setStatus = s => {
    const was = state.status;
    state.status = s; st.textContent = s; st.className = "st " + s;
    replyBox.hidden = s !== "idle";
    stop.textContent = s === "idle" ? "End run" : "Stop";
    stop.hidden = !ACTIVE.includes(s);
    const mine = ACTIVE.includes(s);
    if (mine) activeClaude = { id: run.id, name: run.name, status: s };
    else if (activeClaude && activeClaude.id === run.id) activeClaude = null;
    refreshSkillButtons();
    // A turn has ended, or the run has: what it wrote shows in the other tabs,
    // and what it filed, here.
    if (!mine || (s === "idle" && WORKING.includes(was))) {
      if (loaded.digests) loadDigests();
      if (loaded.applications) loadApplications();
      setupState();
      if (state.replayed) showFiled();
    }
  };
  setStatus(run.status);

  stop.onclick = async () => { try { await api(`/api/claude/${run.id}/stop`, { method: "POST" }); } catch (e) { say(e.message, true); } };
  const doSend = async () => {
    const text = reply.value.trim(); if (!text) return;
    try { await api(`/api/claude/${run.id}/say`, { method: "POST", body: JSON.stringify({ text }) }); reply.value = ""; }
    catch (e) { say(e.message, true); }
  };
  send.onclick = doSend;
  // isComposing: Return that ends a word being composed (Japanese, Chinese, an
  // accent) picks the word, and sends nothing.
  reply.onkeydown = ev => { if (!TOUCH && ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); doSend(); } };

  function render(ev) {
    state.seen = ev.i + 1;
    switch (ev.kind) {
      case "status": setStatus(ev.status); break;
      case "init": transcript.append(el("div", { class: "note" }, `session ${ev.session_id || ""} · ${ev.model || ""}`)); break;
      case "route": transcript.append(el("div", { class: "note" }, `${(ev.label || "").replace(" · ", " at ")} effort: ${ev.why}`)); break;
      case "limits": refreshUsageSoon(); break;
      case "user": transcript.append(el("div", { class: "bubble user" }, ev.text)); break;
      case "text": transcript.append(el("div", { class: "bubble assistant md", html: markdown(ev.text) })); break;
      case "tool_use": {
        const d = el("details", { class: "tool" }, el("summary", {}, el("code", {}, ev.name), " ", ev.summary), el("pre", { class: "text small" }, ""));
        state.tools[ev.id] = d; transcript.append(d); break;
      }
      case "tool_result": {
        const d = state.tools[ev.id];
        if (d) { d.querySelector("pre").textContent = ev.excerpt || (ev.ok ? "(no output)" : "(failed)"); d.classList.toggle("failed", !ev.ok); }
        break;
      }
      case "card": cardArea.replaceChildren(cardView(run.id, ev)); if (NARROW.matches && state.replayed && !document.hidden) cardArea.scrollIntoView({ block: "nearest", behavior: "smooth" }); break;
      case "card_answered": cardArea.replaceChildren(); transcript.append(el("div", { class: "note" }, `${ev.decision === "deny" ? "Denied" : "Allowed"}`)); break;
      case "turn_end": setupState(); transcript.append(el("div", { class: "note" }, `turn ended · ${ev.num_turns ?? "?"} steps` + (ev.tokens ? ` · ${fmtTokens(ev.tokens)} tokens` : "") + (ev.cost ? ` · ≈$${ev.cost.toFixed(2)} so far at API prices` : ""))); break;
      case "error": transcript.append(el("div", { class: "bubble error" }, ev.message)); break;
    }
    transcript.scrollTop = transcript.scrollHeight;
  }

  // The run so far, then live from where that ends. A dropped stream (a phone
  // putting the page in the background, the Mac sleeping or changing networks)
  // reconnects in place, from the last event seen, so the transcript and a
  // half-typed reply stay. While the Mac does not answer it tries again, less
  // often each time, up to every 30 seconds, and at once when the page is shown
  // again or the network comes back.
  let es = null, retry = null, backoff = 1500, over = false;
  const later = fn => {
    if (over) return;
    clearTimeout(retry);
    retry = setTimeout(fn, backoff);
    backoff = Math.min(backoff * 2, 30000);
  };
  const finish = () => {
    over = true; clearTimeout(retry);
    document.removeEventListener("visibilitychange", wake);
    window.removeEventListener("online", wake);
  };
  const connect = () => {
    clearTimeout(retry);
    if (over || es) return;
    es = new EventSource(`/api/runs/${run.id}/stream?start=${state.seen}`);
    es.onmessage = ev => { backoff = 1500; try { render(JSON.parse(ev.data)); } catch (e) { /* a malformed line */ } };
    es.addEventListener("done", ev => { es.close(); es = null; setStatus(ev.data); finish(); });
    es.onerror = () => { es.close(); es = null; later(connect); };
  };
  const replay = async () => {
    let full;
    try { full = await api("/api/runs/" + run.id); }
    catch (e) {
      // A server that no longer knows the run has restarted, and the page reloads (heartbeat).
      if (e.status === 404) { say(e.message, true); finish(); } else later(replay);
      return;
    }
    for (const ev of full.output) if (ev.i >= state.seen) render(ev);
    setStatus(full.status);
    state.replayed = true;
    showFiled(WORKING.includes(full.status) ? null : full.updated);
    if (ACTIVE.includes(full.status)) connect(); else finish();
  };
  const wake = () => {
    if (document.hidden || over || es) return;
    backoff = 1500;
    if (state.replayed) connect(); else replay();
  };
  document.addEventListener("visibilitychange", wake);
  window.addEventListener("online", wake);
  replay();
}

function cardView(runId, card) {
  const box = el("div", { class: "card" + (card.guard ? " guard" : "") });
  const answer = async (decision, extra = {}) => {
    for (const b of box.querySelectorAll("button")) b.disabled = true;
    try { await api(`/api/claude/${runId}/answer`, { method: "POST", body: JSON.stringify({ card_id: card.card_id, decision, ...extra }) }); }
    catch (e) { say(e.message, true); for (const b of box.querySelectorAll("button")) b.disabled = false; }
  };

  if (card.card_kind === "question") {
    box.append(el("h4", {}, "Claude asks"));
    const fields = [];
    for (const q of card.questions) {
      const name = "q" + Math.random().toString(36).slice(2, 8);
      const opts = el("div", { class: "options" });
      for (const o of q.options || []) {
        opts.append(el("label", {}, el("input", { type: q.multiSelect ? "checkbox" : "radio", name, value: o.label }), el("span", {}, el("b", {}, o.label), o.description ? el("small", {}, " " + o.description) : null)));
      }
      const other = el("input", { type: "text", placeholder: "Other…" });
      opts.append(el("label", {}, other));
      box.append(el("div", { class: "question" }, el("div", { class: "qtext" }, el("span", { class: "chip" }, q.header || ""), " ", q.question), opts));
      fields.push({ q, opts, other, multi: !!q.multiSelect });
    }
    const sendBtn = el("button", { class: "action primary", onclick: () => {
      const answers = {};
      for (const f of fields) {
        const picked = [...f.opts.querySelectorAll("input:checked")].map(i => i.value);
        const typed = f.other.value.trim();
        answers[f.q.question] = typed ? (f.multi && picked.length ? [...picked, typed] : typed) : (f.multi ? picked : (picked[0] || ""));
      }
      if (Object.values(answers).some(a => !a || (Array.isArray(a) && !a.length))) { say("Answer every question", true); return; }
      answer("allow", { answers });
    } }, "Send answers");
    box.append(el("div", { class: "toolbar" }, sendBtn, el("button", { class: "action", onclick: () => answer("deny", { message: "The user dismissed the question; carry on without it." }) }, "Dismiss")));
    return box;
  }

  const input = card.input || {};
  if (card.guard) box.append(el("h4", {}, `This changes ${card.file}. This is the exact text.`));
  else {
    // A command is shown in full below, so only a file or another tool's summary goes here.
    box.append(el("h4", {}, `Allow ${card.tool}?`));
    const sub = card.tool === "Bash" ? "" : (card.file || card.summary || "");
    if (sub) box.append(el("div", { class: "muted small" }, sub));
  }
  if (card.tool === "Bash") box.append(el("pre", { class: "text" }, input.command || ""), input.description ? el("div", { class: "muted small" }, input.description) : null);
  else if (card.tool === "Edit") box.append(el("div", { class: "diff" }, el("div", {}, el("div", { class: "label" }, "Replace"), el("pre", { class: "text old" }, input.old_string || "")), el("div", {}, el("div", { class: "label" }, "With"), el("pre", { class: "text new" }, input.new_string || ""))));
  else if (card.tool === "Write") box.append(el("pre", { class: "text new" }, input.content || ""));
  else box.append(el("pre", { class: "text" }, JSON.stringify(input, null, 2)));
  // No reason box on Deny: the card says what is being declined, and the reply
  // box is there once Claude's turn ends.
  const bar = el("div", { class: "toolbar" },
    el("button", { class: "action primary", onclick: () => answer("allow") }, card.guard ? "Approve this text" : "Allow once"),
    card.can_always ? el("button", { class: "action", onclick: () => answer("always") }, "Allow always") : null,
    el("button", { class: "action", onclick: () => answer("deny") }, "Deny"));
  box.append(bar);
  return box;
}

// ------------------------------------------------------------ the route
// Each run's model and effort come from ui/router.py: the skill, what it is
// given, and how full the plan is. The pick here overrides it, for this
// browser; "Auto" leaves it to the router.

const MODELS = ["opus", "sonnet", "haiku"], EFFORTS = ["low", "medium", "high", "xhigh", "max"];
const PICK_KEY = "bs-job-search.pick";
let pick = {};
try { pick = JSON.parse(localStorage.getItem(PICK_KEY) || "{}") || {}; } catch (e) { pick = {}; }

function activePick() {
  const out = {};
  for (const k of ["model", "effort"]) if (pick[k] && pick[k] !== "auto") out[k] = pick[k];
  return out;
}

function pickRow() {
  const select = (key, values) => {
    const s = el("select", { "aria-label": key === "model" ? "Model" : "Effort" },
      ...["auto", ...values].map(v => el("option", { value: v }, v === "auto" ? "Auto" : v[0].toUpperCase() + v.slice(1))));
    s.value = pick[key] || "auto";
    s.onchange = () => {
      pick = { ...pick, [key]: s.value };
      try { localStorage.setItem(PICK_KEY, JSON.stringify(pick)); } catch (e) { /* storage off: this page only */ }
      for (const b of document.querySelectorAll("#run-commands .skill")) b.querySelector(".route").replaceWith(routeLine(b.route));
    };
    return s;
  };
  return el("div", { class: "pick", title: "Auto picks a model and effort for each run, and shows why on its button" },
    el("label", {}, "Model ", select("model", MODELS)), el("label", {}, "Effort ", select("effort", EFFORTS)));
}

// A skill button's route: the router's, with the pick laid over it.
function routeLine(route) {
  if (!route) return el("small", { class: "route" }, "");
  const p = activePick(), model = p.model || route.model, effort = p.effort || route.effort;
  const why = p.model && p.effort ? "Your pick, above." : route.why + (p.model || p.effort ? "; the rest is your pick" : "");
  return el("small", { class: "route", title: why }, `${model[0].toUpperCase() + model.slice(1)} · ${effort}`);
}

function fmtTokens(n) { return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n || 0); }

// ----------------------------------------------------------------- usage
// The plan's usage windows in the header. Every request a run makes reports
// them; between runs the server asks Claude Code's /usage, which calls no
// model, so checking uses none of the plan.

const usageEl = $("#usage");
let usageTimer = null;

function renderUsage(u) {
  const names = u.names || {}, ws = u.windows || {};
  const pct = w => Math.round(w.used * 100);
  const known = Object.entries(ws).filter(([, w]) => typeof w.used === "number");
  const shown = known.filter(([k]) => k === "five_hour" || k === "seven_day");
  if (!shown.length) { usageEl.hidden = true; return; }
  const worst = Math.max(...known.map(([, w]) => w.used));
  usageEl.className = "usage" + (worst >= 0.95 ? " bad" : worst >= 0.8 ? " warn" : "");
  usageEl.textContent = shown.map(([k, w]) => `${names[k] || k} ${pct(w)}%`).join(" · ");
  const lines = known.map(([k, w]) => `${names[k] || k}: ${pct(w)}% used` + (w.reset ? " (it has reset since)" : w.resets_at ? `, resets ${new Date(w.resets_at * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}` : ""));
  const t = u.runs && u.runs.today;
  if (t && t.runs) lines.push("", `This page today: ${t.runs} run${t.runs === 1 ? "" : "s"}, ${fmtTokens(t.tokens)} tokens, ≈$${t.cost.toFixed(2)} at API prices`);
  const ago = u.seen ? Math.max(0, Math.round((Date.now() / 1000 - u.seen) / 60)) : null;
  lines.push("", `Your Claude plan's usage, as Claude Code reports it${ago === null ? "" : ago < 1 ? ", just now" : `, ${ago} min ago`}. Click to check again: checking uses none of it.`);
  usageEl.title = lines.join("\n");
  usageEl.hidden = false;
}

async function loadUsage(check = false) {
  if (DEMO) return;
  try {
    let u = await api("/api/usage");
    renderUsage(u);
    if (check || !u.seen || Date.now() / 1000 - u.seen > 600) {
      usageEl.classList.add("checking");
      u = await api("/api/usage/check", { method: "POST" });
      renderUsage(u);
    }
    refreshRoutes();
  } catch (e) { if (check) say(e.message, true); }
  finally { usageEl.classList.remove("checking"); }
}

// A full plan steps routes down, so the skill buttons follow the usage.
async function refreshRoutes() {
  if (!loaded.runs) return;
  let skills;
  try { skills = await api("/api/skills"); } catch (e) { return; }
  for (const s of skills) {
    const b = document.querySelector(`#run-commands .skill[data-skill="${s.name}"]`);
    if (b) { b.route = s.route; b.querySelector(".route").replaceWith(routeLine(s.route)); }
  }
}
usageEl.onclick = () => loadUsage(true);

// A run reports usage on every request; read it once they settle.
function refreshUsageSoon() { clearTimeout(usageTimer); usageTimer = setTimeout(() => loadUsage(), 1500); }

// ----------------------------------------------------------------- setup
// What a new copy needs, in order: Claude Code, the six files /setup writes,
// then what the first scan and the first resume need. The page opens here
// until the needed files are written and reviewed. The checks are doctor.py's;
// the API keys are the one thing this tab writes itself.

const KEY_FIELDS = { app_id: "App ID", app_key: "App key", email: "Email you registered with", api_key: "API key" };
const CHECK_CHIP = { ok: "ok", MISSING: "bad", DRAFT: "warn" };

// How far setup has got, from the fast route. Also counts what is left on the
// tab's button, so the count stays right from any tab.
async function setupState() {
  let s;
  try { s = await api("/api/setup"); } catch (e) { return null; }
  const left = s.files.filter(f => f.state === "draft" || (f.state === "missing" && f.needed)).length;
  $('nav button[data-tab="setup"]').replaceChildren("Setup", left ? el("span", { class: "count", title: `${left} of the files setup writes still to do` }, String(left)) : "");
  return s;
}

// ------------------------------------------------------------ this phone
// Off the Mac, what this device keeps for when the Mac is away (sw.js), and
// this device's choices about it: the profile files' text (kept unless turned
// off) and documents filed in the last 30 days (not kept unless turned on,
// since resumes and letters carry contact details). Forget deletes the copy
// and stops keeping one, after sending what waits in the outbox if it can.

function askThisPhone() {
  const sw = navigator.serviceWorker && navigator.serviceWorker.controller;
  if (sw) sw.postMessage({ type: "ask" });
}

function showThisPhone(kept) {
  const box = $("#this-phone");
  if (box) box.replaceChildren(...thisPhoneView(kept));
}

function thisPhoneView(kept) {
  const head = el("div", { class: "copy-head" }, el("b", {}, "This phone"));
  if (!COPY) return [head, el("p", { class: "small" }, "This phone keeps no copy of the page, so the icon needs your Mac to open. ",
    el("button", { class: "action small", onclick: () => { try { localStorage.removeItem(NO_COPY_KEY); } catch (e) { /* blocked */ } location.reload(); } }, "Keep a copy on this phone"))];
  if (!navigator.serviceWorker.controller) { setTimeout(askThisPhone, 1500); return [head, el("p", { class: "muted small" }, "Saving a copy of the page on this phone…")]; }
  if (!kept) { askThisPhone(); return [head, el("p", { class: "muted small" }, "Checking what this phone keeps…")]; }
  const s = kept.settings;
  const when = kept.savedAt ? new Date(kept.savedAt).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "not yet";
  const used = el("span", {});
  if (navigator.storage && navigator.storage.estimate) navigator.storage.estimate().then(e => { used.textContent = ` It uses about ${fmtSize(e.usage || 0)} here.`; }).catch(() => {});
  const choice = (key, label, about) => {
    const box = el("input", { type: "checkbox", "data-choice": key });
    box.checked = !!s[key];
    box.onchange = () => {
      const sw = navigator.serviceWorker.controller;
      if (!sw) { box.checked = !box.checked; say("This phone's copy is not ready yet; try again in a moment.", true); return; }
      // Both switches as they stand now, so two changes in a row both hold.
      const now = {};
      for (const b of document.querySelectorAll("#this-phone [data-choice]")) now[b.dataset.choice] = b.checked;
      sw.postMessage({ type: "settings", ...s, ...now, [key]: box.checked });
      say(serverGone ? "Saved. It takes effect once your Mac answers." : "Saved. Updating this phone's copy…");
    };
    return el("label", { class: "choice" }, box, el("span", {}, label, el("span", { class: "muted small" }, " " + about)));
  };
  return [head,
    el("p", { class: "small" }, `The icon opens from a copy kept on this phone when your Mac is away. Last saved ${when}.`, used),
    choice("profile", "Keep your profile files on this phone", "(resume facts, stories, profile): readable with the Mac away."),
    choice("documents", `Keep documents filed in the last ${kept.days} days`, `(resumes, letters, prep sheets, postings): they carry your contact details. ${s.documents ? `${kept.documents} kept now.` : ""}`),
    el("div", { class: "toolbar" }, el("button", { class: "action small", onclick: ev => forgetThisPhone(ev.target) }, "Forget this phone's copy"),
      el("span", { class: "muted small" }, "Deletes it all from this phone, and stops keeping one. Removing the icon from the home screen does the same."))];
}

async function forgetThisPhone(btn) {
  btn.disabled = true;
  if (outbox.length && !serverGone) await replay();
  if (outbox.length && !confirm(`${outbox.length === 1 ? "A change" : `${outbox.length} changes`} made on this phone ${outbox.length === 1 ? "has" : "have"} not reached your Mac and will be lost. Forget this phone's copy anyway?`)) { btn.disabled = false; return; }
  try { localStorage.setItem(NO_COPY_KEY, "1"); localStorage.removeItem(OUTBOX_KEY); } catch (e) { /* blocked */ }
  const sw = navigator.serviceWorker.controller;
  if (sw) { sw.postMessage({ type: "forget" }); setTimeout(() => location.reload(), 4000); return; }
  for (const r of await navigator.serviceWorker.getRegistrations()) await r.unregister();
  for (const name of await caches.keys()) if (name.startsWith("bs-job-search-")) await caches.delete(name);
  location.reload();
}

async function loadSetup() {
  const view = $("#setup-view");
  const checking = () => el("div", {}, el("p", { class: "muted small" }, "Checking…"));
  const parts = { claude: checking(), files: checking(), problems: el("div"), scan: checking(), resume: checking(), phone: checking() };
  const ready = el("div");
  const start = el("button", { class: "action primary", disabled: "", onclick: () => startSkill("setup", {}) }, "Set up");
  const copy = el("section", { id: "copy", class: "copy" }, el("p", { class: "muted small" }, "Checking this copy…"));
  view.replaceChildren(
    el("div", { class: "toolbar" }, el("h2", {}, "Set up"), el("button", { class: "action small", onclick: () => loadSetup() }, "Check again")),
    DEMO ? el("p", { class: "banner" }, DEMO.setupNote) : "",
    !DEMO && !ON_MAC ? el("p", { class: "banner" }, "These steps run on your Mac: this page is open on another device, and each command here goes in Terminal on the Mac.") : "",
    fromPhone ? el("p", { class: "banner bad" }, "Setup needs your Mac, and it is not answering.") : "",
    ready,
    CAN_COPY ? el("section", { id: "this-phone", class: "copy" }, ...thisPhoneView(null)) : "",
    copy,
    setupStep("1", "Claude Code", "The page runs your own Claude Code, with your own login, to do the interviewing, scoring and writing.", parts.claude),
    setupStep("2", "Your profile", "Set up interviews you and writes these files. Every write to your resume facts, stories or profile shows you the exact text first and waits for your approval.", el("div", {}, parts.files, parts.problems)),
    setupStep("3", "Before your first scan", "Two free job sources need a key. Each is saved to a gitignored file on this machine, never through Claude.", parts.scan),
    setupStep("4", "Before your first resume", "LaTeX typesets resumes and letters. Setup does not need it, so it can install while you go.", parts.resume),
    setupStep("5", "On your phone", "Optional: Job Search as an icon on your phone's home screen, opening this page from anywhere. The page stays on this Mac.", parts.phone),
  );

  let claude = null, state = null;
  const settle = () => {
    start.disabled = !(claude && claude.available);
    ready.replaceChildren(claude && claude.available && state && state.ready
      ? el("div", { class: "ready" }, el("b", {}, "You are set up. "), "Run a scan whenever you like; every skill is in the Runs tab.",
          el("div", { class: "toolbar" }, el("button", { class: "action primary", onclick: () => startSkill("job-scan", {}) }, "Job scan"), el("button", { class: "action", onclick: () => showTab("digests") }, "Digests")))
      : "");
  };
  if (DEMO) copy.replaceChildren(...copyView(null));
  else if (copyState) showCopy(copyState);
  loadCopy();
  api("/api/claude/status").catch(e => ({ available: false, reason: e.message }))
    .then(s => { claude = s; parts.claude.replaceChildren(...claudeView(s)); settle(); });
  const stated = setupState().then(s => { state = s; parts.files.replaceChildren(...(s ? filesView(s, start) : [el("p", { class: "muted" }, "Could not read how far setup has got.")])); settle(); });

  if (DEMO) { for (const k of ["scan", "resume", "phone"]) parts[k].replaceChildren(el("p", { class: "muted small" }, "Checked on your own copy.")); return; }
  api("/api/phone").then(s => parts.phone.replaceChildren(...phoneView(s)))
    .catch(e => parts.phone.replaceChildren(el("p", { class: "muted small" }, e.message)));
  let checks;
  try { checks = await api("/api/setup/checks"); }
  catch (e) { parts.scan.replaceChildren(el("p", { class: "muted" }, e.message)); parts.resume.replaceChildren(); return; }
  const rows = group => checks.checks.filter(r => r.group === group);
  parts.scan.replaceChildren(...checks.keys.map(keyForm), el("ul", { class: "checks" }, ...rows("sources").map(checkRow)));
  const noLatex = rows("latex").some(r => r.status === "MISSING");
  // Where the button installs it, the button says how, so the rows need not.
  const latex = rows("latex").map(r => noLatex && checks.latex_install ? { ...r, fix: "" } : r);
  parts.resume.replaceChildren(el("ul", { class: "checks" }, ...latex.map(checkRow)),
    noLatex && checks.latex_install ? el("div", { class: "toolbar" },
      el("button", { class: "action primary", onclick: () => startRun("latex", {}, true) }, "Install LaTeX"),
      el("span", { class: "muted small" }, "TinyTeX, in your home folder: about 64 MB, a few minutes, and no password. It runs in the Runs tab; once it is done, come back and press Check again. Nothing needs restarting."))
    : noLatex ? el("p", { class: "muted small" }, "Once it is installed, press Check again. Nothing needs restarting.") : "");
  // A file that is there but does not load, or Python missing a package: show it with the
  // files. A file not written yet is already in the list above.
  await stated;
  const unwritten = new Set((state ? state.files : []).filter(f => f.state === "missing").map(f => f.path));
  const broken = [...rows("python"), ...rows("profile")].filter(r => r.status === "MISSING" && !unwritten.has(r.what));
  parts.problems.replaceChildren(broken.length ? el("ul", { class: "checks" }, ...broken.map(checkRow)) : "");
}

function setupStep(n, title, about, body) {
  return el("section", { class: "step" }, el("div", { class: "num" }, n),
    el("div", { class: "step-body" }, el("h3", {}, title), el("p", { class: "muted small" }, about), body));
}

function claudeView(s) {
  if (DEMO) return [el("p", { class: "muted small" }, "On your own copy, this says whether Claude Code is ready, and the command to run if not.")];
  if (s.available) return [el("p", {}, el("span", { class: "chip ok" }, "ready"), ` ${s.version || "Claude Code"} · ${s.how}` + (s.logged_in ? " · logged in" : ""))];
  if (s.install) return [
    el("p", {}, el("span", { class: "chip bad" }, "not installed"), " Install it in Terminal (in Applications, Utilities), then press Check again. If the page runs in a Terminal window of its own, use a new one. It needs a paid Claude plan or an Anthropic Console account."),
    command(s.install),
    el("p", { class: "muted small", html: 'Other ways to install it are in <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener">Claude Code\'s setup guide</a>.' })];
  if (s.plan === "free") return [
    el("p", {}, el("span", { class: "chip bad" }, "Free plan"), " " + s.reason),
    el("p", { class: "muted small" }, "To sign in with a Console account, run this in Terminal on the Mac:"),
    command(s.login_console)];
  if (s.login) return [
    el("p", {}, el("span", { class: "chip bad" }, "not logged in"), " Run one of these once in Terminal on the Mac (in Applications, Utilities). It opens your browser to sign in; then press Check again. If the page runs in a Terminal window of its own, use a new one."),
    el("p", { class: "muted small" }, "With a Claude plan (Pro, Max, Team or Enterprise):"), command(s.login),
    el("p", { class: "muted small" }, "With an Anthropic Console account:"), command(s.login_console),
    el("p", { class: "muted small" }, "The Claude desktop app's own login does not carry over to it.")];
  return [el("p", {}, el("span", { class: "chip bad" }, "not available"), " " + (s.reason || ""))];
}

// Phone access (ui/phone.py): Tailscale carries the phone to this Mac, and
// launchd starts the page when it is asked for. When it is set up but does not
// work, `why` says why and what to do, as the installer does. Each command
// starts with its `cd`, so it works from a new Terminal window.
function phoneView(s) {
  if (!s.mac) return [el("p", { class: "muted small" }, "Phone access is set up on a Mac for now.")];
  const awake = el("p", { class: "muted small" }, s.awake);
  if (s.ready) return [
    el("p", {}, el("span", { class: "chip ok" }, "ready"), ` On your phone, with the Tailscale app signed in as ${s.remote.login}: open this in Safari (Chrome on Android), then Share, Add to Home Screen.`),
    command(s.url), awake,
    el("p", { class: "muted small" }, s.recover),
    el("p", { class: "muted small" }, "To turn it off, run this in Terminal on the Mac:"), command(s.disable)];
  const ts = s.tailscale || {};
  if (s.protected) return [
    el("p", {}, el("span", { class: "chip warn" }, "move the copy first"), ` This copy is in ${s.protected}, which macOS does not let anything started in the background open, so the page could not start for your phone. Move it to a folder of its own, then set phone access up there. Close the page first; this remakes Job Search on the Desktop for the new place:`),
    command(s.move)];
  if (s.why) return [
    el("p", {}, el("span", { class: "chip warn" }, s.why.label), " " + s.why.text),
    s.why.code === "tailscale" ? awake : command(s.setup)];
  return [
    el("p", {}, el("span", { class: "chip" }, "not set up"), " The free Tailscale app, on this Mac and on your phone, carries your phone to this page privately: only your own devices can reach it. Set it up in Terminal on the Mac:"),
    command(s.setup),
    ts.found ? "" : el("p", { class: "muted small", html: 'It asks you to install Tailscale first: from the Mac App Store, or from <a href="https://tailscale.com/download" target="_blank" rel="noopener">tailscale.com/download</a> if you are an administrator of the Mac.' })];
}

function filesView(s, start) {
  const list = el("ul", { class: "checks" });
  for (const f of s.files) {
    const chip = f.state === "done" ? el("span", { class: "chip ok" }, "done")
      : f.state === "draft" ? el("span", { class: "chip warn" }, "draft")
      : el("span", { class: "chip" }, f.needed ? "to do" : "optional");
    const more = f.state === "draft" ? " · written, not yet reviewed" : f.state === "missing" && !f.needed ? " · only cover letters need it" : "";
    list.append(el("li", {}, chip, " ", el("code", {}, f.path), el("span", { class: "muted" }, ` · ${f.about}${more}`)));
  }
  const written = s.files.filter(f => f.state !== "missing").length;
  const note = s.ready ? (written < s.files.length
      ? "Everything a scan and a resume need is written. Set up again to add the stories for cover letters, or to change a file after a new job or a move."
      : "All written and reviewed. Set up again to change one, after a new job or a move.")
    : written ? "Set up picks up where it stopped, and asks before changing anything already written."
    : "Doing it properly takes an hour or more, most of it on your resume: every tailored resume is chosen from what you give it here. You can stop after any step, and Set up picks up where you left off.";
  // The resume setup builds to check master.md: the skill cannot show a PDF, so the tab
  // does, inline as the Applications tab does, since not every browser opens a new tab.
  let test = "";
  if (s.test_resume) {
    const url = "/api/setup/test-resume?v=" + s.test_resume.modified;
    const shown = el("div");
    const open = el("a", { href: url, onclick: ev => {
      ev.preventDefault();
      const showing = !!shown.firstChild;
      shown.replaceChildren(showing ? "" : el("iframe", { class: "pdf", src: url }));
      open.textContent = showing ? "Open the test resume" : "Close the test resume";
    } }, "Open the test resume");
    test = el("div", {}, el("p", { class: "small" }, open, el("span", { class: "muted" }, " · every bullet in master.md, built by setup to check it")), shown);
  }
  return [list, test, el("div", { class: "toolbar" }, start, el("span", { class: "muted small" }, note))];
}

function checkRow(r) {
  return el("li", {}, el("span", { class: "chip " + (CHECK_CHIP[r.status] || "") }, r.status.toLowerCase()), " ", el("b", {}, r.what),
    r.detail ? el("span", { class: "muted" }, " · " + r.detail) : null,
    r.fix && r.status !== "ok" ? el("div", { class: "fix" }, r.fix) : null);
}

// A command to run in a terminal, with a button that copies it. Some browsers
// refuse the clipboard API to a page like this one; then the old copy command,
// and failing that, the command selected for the person to copy.
function command(text) {
  const code = el("code", {}, text);
  const copy = el("button", { class: "action small", onclick: async () => {
    try { await navigator.clipboard.writeText(text); say("Copied"); return; } catch (e) { /* below */ }
    const range = document.createRange();
    range.selectNodeContents(code);
    const sel = window.getSelection();
    sel.removeAllRanges(); sel.addRange(range);
    let done = false;
    try { done = document.execCommand("copy"); } catch (e) { /* not supported */ }
    say(done ? "Copied" : "Selected: press Ctrl+C, or ⌘C on a Mac, to copy it");
  } }, "Copy");
  return el("div", { class: "cmd" }, code, copy);
}

// One source's key: typed here, saved by the server into the source's
// gitignored file. The page never reads a saved key back.
function keyForm(k) {
  const inputs = k.fields.map(f => el("input", { type: f.endsWith("key") ? "password" : "text", placeholder: KEY_FIELDS[f] || f, "aria-label": `${k.label} ${KEY_FIELDS[f] || f}`, autocomplete: "off", spellcheck: "false" }));
  const save = el("button", { class: "action" }, k.saved ? "Replace" : "Save");
  save.onclick = async () => {
    const values = Object.fromEntries(k.fields.map((f, i) => [f, inputs[i].value.trim()]));
    if (Object.values(values).some(v => !v)) { say(`Fill in both ${k.label} fields`, true); return; }
    save.disabled = true;
    try { const r = await api("/api/keys/" + k.source, { method: "PUT", body: JSON.stringify(values) }); say(`Saved to ${r.saved}`); loadSetup(); }
    catch (e) { say(e.message, true); save.disabled = false; }
  };
  for (const i of inputs) i.onkeydown = ev => { if (ev.key === "Enter") save.click(); };
  const on = k.on === true ? " · on in filters.yaml" : k.on === false ? " · off in filters.yaml" : "";
  return el("div", { class: "key" },
    el("div", {}, el("span", { class: "chip " + (k.saved ? "ok" : k.on ? "bad" : "") }, k.saved ? "saved" : "no key"), " ", el("b", {}, k.label),
      el("span", { class: "muted small" }, on + " · "), el("a", { href: k.signup, target: "_blank", rel: "noopener" }, "register free"),
      k.saved ? el("span", { class: "muted small" }, ` · in ${k.file}`) : null),
    el("div", { class: "key-form" }, ...inputs, save));
}

// -------------------------------------------------------------- the copy
// Updates from the template, and backups to a repository of the user's own,
// so nobody has to run git. The server fetches quietly when the page opens and
// hourly after; Update and Back up run git there, and stop, changing nothing,
// when something of the user's is in the way. ui/core.py says how.

const copyNote = $("#copy-note");
const COPY_STALE = 3600;   // seconds before the page asks the template again
const RESTART_HOW = "This page is still running the code from before the update. To finish, start it again: stop it with Ctrl+C in the window it runs in (or close that window), then start it the same way, with start.command (start.cmd on Windows) or uv run ui/server.py in this folder.";
const RESTART_APP = "This page is still running the code from before the update. Restart it to finish: a few seconds, or a minute or two when the update added packages.";
let copyState = null, copyLoading = null;

// The page asks on load and from the Setup tab at once: they share one check.
function loadCopy(check = false) {
  if (!copyLoading || check) copyLoading = fetchCopy(check).finally(() => { copyLoading = null; });
  return copyLoading;
}

async function fetchCopy(check) {
  if (DEMO) return null;
  let s;
  try {
    s = await api("/api/copy");
    if (s.layout !== "none" && (check || !s.checked || Date.now() / 1000 - s.checked > COPY_STALE)) {
      showCopy(s);
      s = await api("/api/copy/check", { method: "POST" });
    }
  } catch (e) { return null; }
  showCopy(s);
  return s;
}

// The header's notice, and the Setup tab's box when the tab is open.
function showCopy(s) {
  copyState = s;
  const t = s.template || {}, b = s.backup || {}, n = t.behind || 0;
  const text = s.restart ? "Restart the page" : n ? (t.unit === "files" ? "Update ready" : `${n} update${n === 1 ? "" : "s"}`) : b.behind ? "Newer backup" : "";
  copyNote.textContent = text;
  copyNote.hidden = !text;
  copyNote.className = "usage " + (s.restart ? "warn" : "news");
  copyNote.title = s.restart ? restartHow() : n ? "The template has updates: click for what changed, and the Update button." : "Another machine backed up changes this one does not have yet: click to bring them in.";
  const box = $("#copy");
  if (box) box.replaceChildren(...copyView(s));
}
copyNote.onclick = () => showTab("setup");

function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }
function cap(s) { return s ? s[0].toUpperCase() + s.slice(1) : s; }

function fileList(paths, max = 8) {
  const shown = paths.length > max ? paths.slice(0, max - 1) : paths;
  return el("ul", { class: "copy-files" }, ...shown.map(p => el("li", {}, p)), paths.length > shown.length ? el("li", { class: "muted" }, `and ${paths.length - shown.length} more`) : null);
}

function copyView(s) {
  if (!s) return [el("p", { class: "muted small" }, "On your own copy, this says when the template has updates and brings them in, and backs your work up to a repository of your own.")];
  const result = el("div", { class: "copy-result" });
  const check = s.layout === "none" ? null : el("button", { class: "action small", onclick: () => copyAct(check, "/api/copy/check", "POST") }, "Check now");
  const ago = s.checked ? Math.round((Date.now() / 1000 - s.checked) / 60) : null;
  const parts = [el("div", { class: "copy-head" }, el("b", {}, "Your copy"), check,
    el("div", { class: "muted small" }, s.about + (ago === null ? "" : ago < 1 ? " Checked just now." : ` Checked ${ago} min ago.`)))];
  if (s.restart) parts.push(el("p", { class: "banner warn" }, el("b", {}, "Restart the page. "), restartHow(),
    HEALTH && HEALTH.restart ? el("span", {}, " ", el("button", { class: "action small primary", onclick: ev => restartPage(ev.target) }, "Restart now")) : ""));
  if (s.error) parts.push(el("p", { class: "fix" }, s.error));
  if (s.layout === "unlinked") {
    const link = el("button", { class: "action", onclick: () => copyAct(link, "/api/copy/link", "POST") }, "Link to the template");
    parts.push(el("div", { class: "copy-row" }, el("span", { class: "chip" }, "no updates"), " Link it to get the template's updates. ", link,
      el("div", { class: "muted small" }, "For a copy made with GitHub's Use this template, or one whose link to the template was removed.")));
  } else if (s.template) parts.push(updateRow(s));
  if (s.backup) parts.push(backupRow(s));
  const t = s.template || {}, b = s.backup || {};
  // A name is needed to commit or merge: a backup does both, and an update merges once the copy has commits of its own.
  if (!s.identity && s.branch && (b.remote || (t.behind && b.unpushed))) parts.push(identityForm());
  parts.push(result);
  return parts;
}

function updateRow(s) {
  const t = s.template, b = s.backup || {};
  if (t.behind === null) return el("div", { class: "copy-row" }, el("span", { class: "chip" }, "not checked"), " Not checked against the template yet.");
  const n = t.behind, mine = b.behind || 0;
  if (!n && !mine) return el("div", { class: "copy-row" }, el("span", { class: "chip ok" }, "up to date"), ` With the template${t.version ? ", " + t.version : ""}.`);
  const what = [];
  if (mine) what.push(`${plural(mine, "change")} backed up from another machine`);
  if (n) what.push((t.unit === "files" ? `${plural(n, "file")} of the template's to bring in` : `${plural(n, "update")} from the template`) + (t.version ? `, up to ${t.version}` : ""));
  const go = el("button", { class: "action primary", disabled: s.branch ? null : "", onclick: () => copyAct(go, "/api/copy/update", "POST") }, "Update");
  const row = el("div", { class: "copy-row" }, el("span", { class: "chip warn" }, "update"), " " + cap(what.join(", and ")) + ". ", go);
  const blocked = [...new Set([...(b.blocked || []), ...(t.blocked || [])])];
  if (blocked.length) row.append(el("div", { class: "fix" }, "It will stop, changing nothing, until these are committed or undone: they have changes on this machine it would write over."), fileList(blocked));
  if (t.conflicts && t.conflicts.length) row.append(el("div", { class: "fix" }, "It will stop, changing nothing, at these: they were changed in this copy, and the template has changed them since."), fileList(t.conflicts));
  if (t.notes && t.notes.length) row.append(el("details", { class: "notes" }, el("summary", {}, "What's new"),
    ...t.notes.map(x => el("div", { class: "note-entry" }, el("b", {}, x.subject), x.body ? el("div", { class: "md", html: markdown(x.body) }) : null))));
  return row;
}

function backupRow(s) {
  const b = s.backup, mine = b.changes.length, pushed = b.unpushed;
  if (!b.remote) {
    if (!mine && !pushed) return "";
    return el("div", { class: "copy-row" }, el("span", { class: "chip" }, "this machine only"),
      ` ${mine ? `${plural(mine, "file")} of yours ${mine === 1 ? "is" : "are"}` : "Your work is"} not backed up anywhere. `,
      el("a", { href: s.help, target: "_blank", rel: "noopener" }, "How to back up, or use a second machine"));
  }
  const pending = [];
  if (mine) pending.push(`${plural(mine, "file")} changed`);
  if (pushed) pending.push(`${plural(pushed, "saved change")} not pushed yet`);
  const row = el("div", { class: "copy-row" });
  if (!pending.length) row.append(el("span", { class: "chip ok" }, "backed up"), ` To ${b.url}.`);
  else {
    row.append(el("span", { class: "chip warn" }, "not backed up"), ` ${cap(pending.join(", and "))} since the last backup, to ${b.url}.`);
    if (mine) row.append(fileList(b.changes));
    const msg = mine ? el("input", { type: "text", placeholder: "What changed, in a few words: it labels this backup", "aria-label": "What changed", maxlength: "2000" }) : null;
    const go = el("button", { class: "action primary", disabled: s.branch ? null : "" }, "Back up now");
    go.onclick = () => {
      if (msg && !msg.value.trim()) { say("Say in a few words what changed", true); msg.focus(); return; }
      copyAct(go, "/api/copy/backup", "POST", { message: msg ? msg.value.trim() : null });
    };
    if (msg) msg.onkeydown = ev => { if (ev.key === "Enter") go.click(); };
    row.append(el("div", { class: "key-form" }, msg, go));
  }
  if (b.other.length) row.append(el("div", { class: "muted small" }, `Not part of a backup: your changes to the template's own files (${b.other.slice(0, 4).join(", ")}${b.other.length > 4 ? ", …" : ""}).`));
  row.append(el("div", { class: "muted small" }, "Applications/ is not part of a backup either: keep a copy of that folder somewhere else."));
  return row;
}

function identityForm() {
  const name = el("input", { type: "text", placeholder: "Your name", "aria-label": "Your name", autocomplete: "name" });
  const email = el("input", { type: "email", placeholder: "Your email", "aria-label": "Your email", autocomplete: "email" });
  const save = el("button", { class: "action" }, "Save");
  save.onclick = () => {
    if (!name.value.trim() || !email.value.trim()) { say("Give a name and an email", true); return; }
    copyAct(save, "/api/copy/identity", "PUT", { name: name.value.trim(), email: email.value.trim() });
  };
  return el("div", { class: "copy-row" }, el("span", { class: "chip warn" }, "name needed"),
    " Git labels each update and backup in this copy's history with a name and an email, and has neither yet. Any address works; GitHub's no-reply one keeps yours out of the history.",
    el("div", { class: "key-form" }, name, email, save));
}

// One of the box's buttons: run it, show the copy as it now stands, and say
// what happened. A 409 is a stop: nothing was changed.
async function copyAct(btn, path, method, body) {
  for (const b of document.querySelectorAll("#copy button")) b.disabled = true;
  btn.textContent = { "/api/copy/update": "Updating…", "/api/copy/backup": "Backing up…", "/api/copy/check": "Checking…", "/api/copy/link": "Linking…" }[path] || "Saving…";
  let r, problem = null;
  try { r = await api(path, { method, body: body ? JSON.stringify(body) : undefined }); }
  catch (e) { problem = (e.status === 409 ? "Stopped, and nothing was changed. " : "") + e.message; }
  if (problem) { showCopy(copyState); copyResult("bad", problem); return; }
  showCopy(r.status || r);
  if (r.message) copyResult(r.ok ? "ok" : "warn", r.message, r.reload);
  if (r.changed && r.changed.length) { if (loaded.digests) loadDigests(); if (loaded.profile) loadProfile(); setupState(); }
}

function copyResult(kind, text, reload = false) {
  const box = $("#copy .copy-result");
  if (!box) { say(text, kind === "bad"); return; }
  box.className = "copy-result " + kind;
  box.replaceChildren(text, reload ? el("button", { class: "action small", onclick: () => location.reload() }, "Reload the page") : "");
  if (reload) box.prepend(el("div", { class: "muted small" }, "The page's own files changed: reload it to see them."));
}

// --------------------------------------------------------------- profile

async function loadProfile() {
  const list = $("#profile-list");
  list.replaceChildren();
  let files;
  try { files = await api("/api/profile"); } catch (e) { say(e.message, true); return; }
  for (const f of files) {
    list.append(el("button", { class: "item", disabled: f.exists ? null : "", onclick: ev => openProfileFile(f.path, ev.currentTarget) }, f.path, el("small", {}, f.exists ? f.about : "not written yet")));
  }
}

async function openProfileFile(path, btn) {
  for (const b of document.querySelectorAll("#profile-list .item")) b.classList.toggle("active", b === btn);
  pickSide("profile", path);
  const view = $("#profile-view");
  view.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  try {
    const text = await api("/api/profile/" + path);
    view.replaceChildren(path.endsWith(".md") ? el("div", { class: "md", html: markdown(text) }) : el("pre", { class: "text" }, text));
  } catch (e) { view.replaceChildren(el("p", { class: "muted" }, e.message)); }
}

// -------------------------------------------------------------- markdown
// Enough for the digests and the profile files: headings, rules, quotes,
// tables, lists, fenced code, and inline bold, italics, code, and links.

function esc(s) { return s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:]|$)/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}

function markdown(text) {
  if (!text) return "";
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;
  const para = [];
  const flush = () => { if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para.length = 0; } };
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (line.startsWith("```")) {
      flush(); const code = []; i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++; out.push("<pre><code>" + esc(code.join("\n")) + "</code></pre>"); continue;
    }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { flush(); const h = Math.min(m[1].length, 3); out.push(`<h${h}>${inline(m[2])}</h${h}>`); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
    if (line.startsWith("<!--")) { flush(); while (i < lines.length && !lines[i].includes("-->")) i++; i++; continue; }
    if (line.startsWith("> ")) { flush(); const q = []; while (i < lines.length && lines[i].startsWith(">")) q.push(lines[i++].replace(/^>\s?/, "")); out.push("<blockquote>" + markdown(q.join("\n")) + "</blockquote>"); continue; }
    if (line.startsWith("|")) {
      flush(); const rows = []; while (i < lines.length && lines[i].startsWith("|")) rows.push(lines[i++]);
      const cells = r => r.replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const body = rows.filter(r => !/^\|[\s:|-]+\|$/.test(r));
      out.push("<table>" + body.map((r, k) => "<tr>" + cells(r).map(c => `<${k ? "td" : "th"}>${inline(c)}</${k ? "td" : "th"}>`).join("") + "</tr>").join("") + "</table>"); continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      flush(); const items = [];
      while (i < lines.length && (/^\s*([-*]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (/^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        else items[items.length - 1] += " " + lines[i].trim();
        i++;
      }
      out.push("<ul>" + items.map(t => "<li>" + inline(t.replace(/^\[([ xX])\]\s*/, (_, c) => c === " " ? "☐ " : "☑ ")) + "</li>").join("") + "</ul>"); continue;
    }
    if (!line.trim()) { flush(); i++; continue; }
    para.push(line); i++;
  }
  flush();
  return out.join("\n");
}

// ------------------------------------------------------------ the server
// The page asks /api/health once a minute, which keeps a server started with
// --idle-exit (Job Search on the Desktop) up while any tab is open. When the
// server does not answer, a banner says why that may be and how to start it
// again. When it answers again, the page reloads only if it is another server
// than the one it loaded from (a new `started`); the same one, back after a
// blip, carries on as it was, with anything typed still there.

let HEALTH = null, serverGone = false, restarting = false, gonePoll = null;

// Off the Mac, what the page reads may come from this device's copy (sw.js)
// while the Mac is away. A read answered from the copy says so, and when the
// copy was saved; the banner shows that until the Mac answers again, when the
// worker takes a fresh snapshot and the page redraws what it has loaded.

let fromPhone = null;      // when the copy being shown was saved, while the Mac has not answered
let refreshTimer = null, refreshWanted = false;

function noteServed(r) {
  if (!COPY || fromPhone || r.headers.get("X-Served-From") !== "phone") return;
  fromPhone = r.headers.get("X-Saved-At") || "unknown";
  serverBanner(copyText(), false);
}

function copyText() {
  const at = fromPhone && fromPhone !== "unknown" ? new Date(fromPhone) : null;
  const when = at && !isNaN(at) ? at.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "an earlier visit";
  return serverGone
    ? `Your Mac isn't answering (asleep, offline, or Tailscale is off), so this is the phone's copy from ${when}. Reading works; a change needs the Mac, and this page picks up by itself once it answers.`
    : `Showing this phone's copy from ${when} while your Mac is asked.`;
}

// The Mac answers again: what waited here goes to it, the worker takes a
// fresh snapshot, and the page redraws.
function macBack() {
  fromPhone = null;
  serverBanner("");
  replaySoon(0);
  if (navigator.serviceWorker && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ type: "refresh" });
  refreshSoon();
}

// Redraw what is loaded from what the Mac says now: the digests and the one
// open, the applications, the profile list, and the runs. Not while something
// is being typed: then once it is left.
function refreshSoon() { refreshWanted = true; clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshViews, 400); }
function typing() { const a = document.activeElement; return !!a && ["INPUT", "TEXTAREA", "SELECT"].includes(a.tagName); }
async function refreshViews() {
  if (!refreshWanted || typing()) return;
  refreshWanted = false;
  if (loaded.digests) { await loadDigests(); if (currentDigest) await openDigest(currentDigest); }
  if (loaded.applications) loadApplications();
  if (loaded.profile) loadProfile();
  if (loaded.runs) loadRuns();
}
document.addEventListener("focusout", () => { if (refreshWanted) setTimeout(refreshViews, 300); });

if (COPY) navigator.serviceWorker.addEventListener("message", e => {
  const m = e.data || {};
  if (m.type === "kept") showThisPhone(m);
  else if (m.type === "settings") { askThisPhone(); refreshSoon(); }
  else if (m.type === "forgotten") location.reload();
  else if (m.type === "fresh") refreshSoon();
  else if (m.type === "copied") say("This phone keeps a copy of the page now: it opens from it when your Mac is away.");
  // The page's own files changed on the Mac (an update): this copy's code is out of date.
  else if (m.type === "page" && !typing()) location.reload();
});


function serverBanner(text, bad = false) {
  let b = $("#server-banner");
  if (!text) { if (b) b.remove(); return; }
  if (!b) { b = el("div", { id: "server-banner", class: "server-banner" }); document.body.prepend(b); }
  b.className = "server-banner" + (bad ? " bad" : "");
  b.textContent = text;
}

function restartHow() { return HEALTH && HEALTH.restart ? RESTART_APP : RESTART_HOW; }

function goneText() {
  if (!ON_MAC) return "Can't reach your Mac. It may be asleep or offline, or Tailscale may be off on this phone or on the Mac. This page picks up by itself once it answers.";
  if (HEALTH && HEALTH.launchd) return "The page is not answering. Open Job Search on your Desktop, or restart the Mac if that does not bring it back, and this tab picks up by itself.";
  if (HEALTH && HEALTH.restart) return "The page has stopped: it stops by itself ten minutes after its last tab closes, and a browser can pause a tab it has hidden for long. Open Job Search on your Desktop to start it again, and this tab picks up by itself.";
  return "The page has stopped. Start it again (start.command, or Job Search on your Desktop), and this tab picks up by itself.";
}

// /api/health, or null. A Mac out of reach can leave a request hanging for a
// minute or more, so it gives up after 20 seconds, which is still time enough
// for launchd to start the page from cold.
async function askHealth(ms = 20000) {
  const ctl = window.AbortController ? new AbortController() : null;
  const timer = ctl && setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch("/api/health", { cache: "no-store", signal: ctl ? ctl.signal : undefined });
    if (r.ok) return await r.json();
  } catch (e) { /* not answering */ }
  finally { clearTimeout(timer); }
  return null;
}

let beating = false;
async function heartbeat() {
  if (beating) return;   // one at a time: a slow answer is not a reason to ask again
  beating = true;
  try { await beat(); } finally { beating = false; }
}

async function beat() {
  let h = await askHealth();
  // One miss is often a blip, as when a phone wakes the page: ask once more first.
  if (!h && !serverGone && !restarting && !fromPhone) { await new Promise(r => setTimeout(r, 2000)); h = await askHealth(); }
  if (h) {
    if (restarting) return;   // restartPage() reloads once the new server answers
    if (HEALTH && h.started !== HEALTH.started) { location.reload(); return; }   // another server: this tab is out of date
    if (serverGone) { serverGone = false; clearInterval(gonePoll); gonePoll = null; serverBanner(""); }
    const first = !HEALTH;
    HEALTH = h;
    if (first && copyState && copyState.restart) showCopy(copyState);   // now it can offer Restart
    if (fromPhone) macBack();
    else replaySoon();
    return;
  }
  if (restarting || serverGone) return;
  serverGone = true;
  serverBanner(fromPhone ? copyText() : goneText(), !fromPhone);
  // Off the Mac each miss costs the whole wait, so ask less often.
  gonePoll = setInterval(heartbeat, ON_MAC ? 5000 : 15000);
}

async function restartPage(btn) {
  if (btn) btn.disabled = true;
  const before = HEALTH && HEALTH.started;
  try { await api("/api/restart", { method: "POST" }); }
  catch (e) { say(e.message, true); if (btn) btn.disabled = false; return; }
  restarting = true;
  serverBanner("Restarting the page. Installing what an update added can take a minute or two; this tab reloads by itself.");
  const until = Date.now() + 10 * 60 * 1000;
  const poll = async () => {
    try { const h = await (await fetch("/api/health")).json(); if (h.started !== before) { location.reload(); return; } } catch (e) { /* not back yet */ }
    if (Date.now() > until) {
      serverBanner(ON_MAC ? "The page has not come back after ten minutes. Open Job Search on your Desktop; what it printed is in ~/Library/Logs/BS Job Search.log."
        : "The page has not come back after ten minutes. Open Job Search on the Mac's Desktop; what it printed is in ~/Library/Logs/BS Job Search.log, on the Mac. If the Mac is asleep or offline, this page cannot reach it.", true);
      return;
    }
    setTimeout(poll, 1500);
  };
  setTimeout(poll, 1500);
}

// ---------------------------------------------------------------- outbox
// Off the Mac, a tick or a status change made while the Mac is away waits
// here, on this device, and goes once the Mac answers: oldest first, one at
// a time, each kept until the Mac takes it. Each carries what the page
// showed when it was made, so the Mac takes it, finds it already holds, or
// refuses it with what is there now, which becomes a card here to settle:
// use this phone's, keep the Mac's, or drop it. A change sent again after
// its answer was lost counts as done: a box already at its value, a status
// already there, an undo whose line is already gone. Nothing else waits
// here: verdicts, keys and runs need the Mac.

const OUTBOX_KEY = "bs-job-search.outbox";
const QUEUED = "Waiting for your Mac: this is kept on the phone and goes to the Mac once it answers.";
const outboxEl = $("#outbox");
let outbox = [];
try { outbox = JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]"); if (!Array.isArray(outbox)) outbox = []; } catch (e) { outbox = []; }

function editId() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
function todayHere() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; }
function markSaid(marks) {
  const boxes = Object.entries(marks).filter(([k]) => k !== "skip_reason").map(([k, v]) => (v ? "" : "not ") + (k === "letter" ? "cover letter" : k));
  return [...boxes, marks.skip_reason ? `reason “${marks.skip_reason}”` : null].filter(Boolean).join(", ") || "no change";
}
function statusSaid(c) { return c.undo ? "undo the last change" : c.status ? c.status + (c.date ? ` on ${c.date}` : "") : c.date ? `dated ${c.date}` : "note" in c ? (c.note ? `note “${c.note}”` : "note cleared") : "no change"; }

function keepOutbox() {
  try { localStorage.setItem(OUTBOX_KEY, JSON.stringify(outbox)); }
  catch (e) { say("This phone could not keep the change: its storage is full or blocked.", true); }
  showOutbox();
}

// Queue one change. A tick joins the one already waiting for the same entry:
// later boxes replace earlier ones, and the first `expect` stays, since that
// is what the page showed before anything waited here. A status given later
// keeps the day it was given, not the Mac's day when it arrives.
function enqueue(edit) {
  if (edit.kind === "status" && edit.body.status && !edit.body.date) edit.body.date = todayHere();
  const same = edit.kind === "mark" ? outbox.find(o => o.kind === "mark" && o.path === edit.path && !o.conflict) : null;
  if (same) { Object.assign(same.body, edit.body, { expect: same.body.expect }); same.label = edit.label; same.at = edit.at; }
  else outbox.push(edit);
  keepOutbox();
}

// Send a change to the Mac, or queue it when the Mac is away: off the Mac, a
// change the Mac did not answer waits rather than being lost.
async function send(edit) {
  const queued = () => { enqueue(edit); return Object.assign(new Error(QUEUED), { queued: true }); };
  if (COPY && serverGone) throw queued();
  try { return await api(edit.path, { method: "PUT", body: JSON.stringify(edit.body) }); }
  catch (err) { throw COPY && !err.status ? queued() : err; }
}

function drop(edit) { outbox = outbox.filter(o => o !== edit); keepOutbox(); }

// Send a refused change again, checked against what the Mac holds now.
function useMine(o) {
  const c = o.conflict.current;
  if (o.kind === "mark") o.body.expect = { apply: !!c.apply, skip: !!c.skip, letter: !!c.letter, skip_reason: c.skip_reason || "" };
  else { o.body.expect_last = c.last || ""; if ("expect_note" in o.body) o.body.expect_note = c.note || ""; }
  delete o.conflict;
  keepOutbox();
  replaySoon(0);
}

let replaying = false, replayTimer = null;
function replaySoon(ms = 300) { if (!outbox.length) return; clearTimeout(replayTimer); replayTimer = setTimeout(replay, ms); }

// Oldest first, one at a time, while the Mac answers and neither a skill nor
// an update holds its files. A refusal with what is there now becomes a card;
// one by the Mac's own rules (a status that cannot go back) is shown, to
// drop; a day the Mac has not reached yet waits for its midnight.
async function replay() {
  if (replaying || !COPY || serverGone || !outbox.some(o => !o.conflict)) return;
  if (HEALTH && (HEALTH.working || HEALTH.git)) { replaySoon(10000); return; }
  replaying = true;
  let sent = 0;
  try {
    for (const edit of outbox.filter(o => !o.conflict)) {
      try { await api(edit.path, { method: "PUT", body: JSON.stringify(edit.body) }); sent++; drop(edit); }
      catch (err) {
        if (!err.status) break;                                    // the Mac went away again: the rest waits
        if (err.status === 409 && err.current) {
          if (edit.kind === "status" && edit.body.undo && (err.current.last || "") === edit.before) { sent++; drop(edit); continue; }
          edit.conflict = { message: err.message, current: err.current, moved: edit.kind === "mark" && "company" in err.current };
        } else if (/after today/.test(err.message)) break;
        else edit.conflict = { message: err.message, current: null };
        keepOutbox();
      }
    }
  } finally { replaying = false; }
  if (sent) {
    say(`Sent ${sent === 1 ? "a change" : `${sent} changes`} from this phone to your Mac.`);
    if (navigator.serviceWorker && navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ type: "refresh" });
    refreshSoon();
  }
  showOutbox();
}

// The header's count, and the panel under it listing what waits, with a card
// for each change the Mac refused.
function showOutbox() {
  const n = outbox.length, c = outbox.filter(o => o.conflict).length;
  outboxEl.hidden = !n;
  outboxEl.className = "usage " + (c ? "bad" : "warn");
  outboxEl.textContent = c ? `${c} to settle` + (n > c ? `, ${n - c} waiting` : "") : `${n} waiting for your Mac`;
  outboxEl.title = "Changes made on this phone that your Mac has not taken yet. Click to see them.";
  const panel = $("#outbox-panel");
  if (panel) { if (n) panel.replaceChildren(...outboxView()); else panel.remove(); }
  else if (c) openOutbox();          // a refusal needs an answer: show it
}
function openOutbox() {
  const open = $("#outbox-panel");
  if (open) { open.remove(); return; }
  const panel = el("div", { id: "outbox-panel", class: "outbox" }, ...outboxView());
  const banner = $("#server-banner");
  if (banner) banner.after(panel); else document.body.prepend(panel);
}
outboxEl.onclick = openOutbox;

function outboxView() {
  const items = outbox.map(o => {
    const when = new Date(o.at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    const item = el("div", { class: "outbox-item" + (o.conflict ? " conflict" : "") }, el("b", {}, o.label), ` · ${when} `);
    if (!o.conflict) { item.append(el("span", { class: "chip warn" }, serverGone ? "waiting for your Mac" : "sending")); return item; }
    item.append(el("div", { class: "small" }, o.conflict.message));
    const mine = o.conflict.current && !o.conflict.moved ? el("button", { class: "action small primary", onclick: () => useMine(o) }, "Use this phone's") : null;
    item.append(el("div", { class: "toolbar" }, mine, el("button", { class: "action small", onclick: () => drop(o) }, mine ? "Keep the Mac's" : "Drop it")));
    return item;
  });
  return [el("div", { class: "outbox-head" }, el("b", {}, "From this phone"),
    el("span", { class: "muted small" }, "Changes your Mac has not taken yet. Removing the icon from the home screen loses them."),
    el("button", { class: "action small", onclick: () => $("#outbox-panel").remove() }, "Close")), ...items];
}
showOutbox();

// A tick or a status change applied to what the page holds, the way the
// Mac would apply it: for the demos, and for a change waiting on this phone.
function localMark(e, marks) {
  for (const [k, field] of [["apply", "marked_apply"], ["skip", "marked_skip"], ["letter", "marked_letter"], ["skip_reason", "skip_reason"]]) {
    if (k in marks) e[field] = marks[k];
  }
}
function markCounts(d) {
  const a = x => x.marked_apply, s = x => x.marked_skip, l = x => x.marked_letter, es = d.entries;
  return {
    date: d.date, entries: es.length,
    apply: es.filter(x => a(x) && !s(x)).length,
    skip: es.filter(x => s(x) && !a(x) && !l(x)).length,
    unmarked: es.filter(x => !a(x) && !s(x) && !l(x)).length,
    conflicts: es.filter(x => (s(x) && (a(x) || l(x))) || (l(x) && !a(x) && !s(x))).length,
  };
}
// The select offers only the moves the tracker takes, and the date input
// keeps the dates in order, so this needs none of the tracker's checks.
function localStatus(data, change) {
  const f = data.folders.find(x => x.company === change.company);
  const r = f && f.roles.find(x => x.role === (change.role || ""));
  if (!r) return null;
  const h = r.history;
  if (change.undo) h.pop();
  if (change.status) h.push({ date: change.date || data.today, status: change.status });
  else if (change.date && h.length) h[h.length - 1].date = change.date;
  if ("note" in change) r.note = change.note.trim().replace(/\s+/g, " ");
  const last = h[h.length - 1] || {};
  const reached = Math.max(0, ...h.map(x => data.stage[x.status] || 0));
  Object.assign(r, {
    status: last.status || null, since: last.date || null, waiting: null,
    applied: (h.find(x => x.status === "applied") || {}).date || null,
    ended: data.ended.includes(last.status),
    moves: data.statuses.filter(s => s !== last.status && (!(s in data.stage) || data.stage[s] > reached)),
  });
  return r;
}

// ----------------------------------------------------------------- start

// A run started from another tab, or resumed from one, shows up here too,
// without a reload. attachRun() skips the ones already on the page.
async function pollRuns() {
  if (!loaded.runs || document.hidden) return;
  try { for (const r of await api("/api/runs")) attachRun(r, ACTIVE.includes(r.status)); }
  catch (e) { /* the server is restarting */ }
}
setInterval(pollRuns, 4000);
// A page shown again (a phone back from the background, a tab brought to the
// front) checks at once rather than at the next tick: the server first, which
// reloads the page if it has restarted meanwhile, then the runs.
document.addEventListener("visibilitychange", () => {
  if (document.hidden || DEMO) return;
  heartbeat().then(pollRuns);
});

// --------------------------------------------------------------- demo
// The demos have no server. Reads come from what the builder bundled, ticking
// a box changes this page only, and anything that would write a file or run
// something says so instead.

const DEMO_NOTE = "This is a demo, so nothing is saved or run. On your own copy it is.";

function demoApi(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  if (path.startsWith("files/")) {
    return fetch(path).then(r => r.ok ? r.text() : Promise.reject(new Error("Not in this demo")));
  }
  if (method === "GET") {
    const found = DEMO.get[path];
    return found === undefined ? Promise.reject(new Error("Not in this demo"))
      : Promise.resolve(JSON.parse(JSON.stringify(found)));
  }
  const m = path.match(/^\/api\/digests\/([^/]+)\/entries\/(\d+)$/);
  if (method === "PUT" && m) return Promise.resolve(demoMark(m[1], Number(m[2]), JSON.parse(opts.body || "{}")));
  if (method === "PUT" && path === "/api/applications/status") return demoStatus(JSON.parse(opts.body || "{}"));
  return Promise.reject(new Error(DEMO_NOTE));
}

// Change a status in the bundled listing, the way scripts/tracker.py does
// without its checks (localStatus).
function demoStatus(change) {
  const data = DEMO.get["/api/applications"];
  if (!localStatus(data, change)) return Promise.reject(new Error("Not in this demo"));
  return Promise.resolve(JSON.parse(JSON.stringify(data)));
}

// Tick a box in the bundled digest, and recount the way core.list_digests does.
function demoMark(date, n, marks) {
  const d = DEMO.get["/api/digests/" + date];
  localMark(d.entries.find(x => x.n === n), marks);
  const counts = markCounts(d);
  Object.assign(DEMO.get["/api/digests"].find(x => x.date === date), counts);
  return counts;
}

if (DEMO && DEMO.banner) document.body.prepend(el("div", { class: "demo-banner", html: DEMO.banner }));

// The first tab: the one the address names, else Setup until the profile is
// written and reviewed, then Digests.
const TABS = ["setup", "digests", "applications", "runs", "profile"];
loadUsage();
loadCopy();
setInterval(() => { if (!document.hidden) loadCopy(); }, 15 * 60 * 1000);
// While a tab has the page open, it says so once a minute, hidden or not, so
// a server started with --idle-exit stays up until every tab is closed.
if (!DEMO) { heartbeat(); setInterval(heartbeat, 60 * 1000); }
// Off the Mac the choice does not wait on a Mac that may be asleep: Digests
// after a moment, and the Setup tab's count fills in when the Mac answers.
const firstState = COPY ? Promise.race([setupState(), new Promise(r => setTimeout(() => r(null), 1500))]) : setupState();
firstState.then(s => {
  const asked = location.hash.slice(1);
  showTab(TABS.includes(asked) ? asked : s && !s.ready ? "setup" : "digests");
});
window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if (TABS.includes(t) && !$("#tab-" + t).classList.contains("active")) showTab(t); });
