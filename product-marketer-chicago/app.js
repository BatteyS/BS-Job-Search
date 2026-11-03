// The page. No framework and no build step: five tabs over /api, each a
// sidebar and a content pane, apart from Setup's single column. Markdown is rendered with the small renderer at
// the bottom, which covers what the digests and profile files use.
//
// The example demos (ui/build_demo.py) run this same file with no server:
// window.DEMO holds what each route would answer, and demoApi() reads it.

const $ = (sel, el = document) => el.querySelector(sel);
const statusEl = $("#status");
const DEMO = window.DEMO || null;

function say(text, isError = false) {
  statusEl.textContent = text;
  statusEl.className = "status" + (isError ? " err" : "");
  if (!isError) setTimeout(() => { if (statusEl.textContent === text) statusEl.textContent = ""; }, 4000);
}

async function api(path, opts = {}) {
  if (DEMO) return demoApi(path, opts);
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* not json */ }
    throw new Error(msg);
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
}

// --------------------------------------------------------------- digests

let currentDigest = null;

async function loadDigests() {
  const list = $("#digest-list");
  list.replaceChildren();
  let digests;
  try { digests = await api("/api/digests"); } catch (e) { say(e.message, true); return; }
  if (!digests.length) { list.append(el("p", { class: "muted" }, "No digests yet. A scan writes one: Job scan, in the Runs tab.")); return; }
  for (const d of digests) {
    const counts = `${d.entries} roles · ${d.apply} apply · ${d.skip} skip` + (d.unmarked ? ` · ${d.unmarked} unmarked` : "") + (d.conflicts ? ` · ${d.conflicts} to settle` : "");
    list.append(el("button", { class: "item", "data-date": d.date, onclick: () => openDigest(d.date) }, d.date, el("small", {}, counts)));
  }
  if (!currentDigest) openDigest(digests[0].date);
}

function refreshDigestCounts(d) {
  const b = $(`#digest-list [data-date="${d.date}"] small`);
  if (b) b.textContent = `${d.entries} roles · ${d.apply} apply · ${d.skip} skip` + (d.unmarked ? ` · ${d.unmarked} unmarked` : "") + (d.conflicts ? ` · ${d.conflicts} to settle` : "");
}

async function openDigest(date) {
  currentDigest = date;
  for (const b of document.querySelectorAll("#digest-list .item")) b.classList.toggle("active", b.dataset.date === date);
  const view = $("#digest-view");
  view.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  let d;
  try { d = await api("/api/digests/" + date); } catch (e) { view.replaceChildren(el("p", { class: "muted" }, e.message)); return; }

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

  async function save(marks) {
    try {
      const counts = await api(`/api/digests/${date}/entries/${e.n}`, { method: "PUT", body: JSON.stringify(marks) });
      Object.assign(e, { marked_apply: apply.checked, marked_skip: skip.checked, marked_letter: letter.checked, skip_reason: reason.value });
      state(); refreshDigestCounts(counts); say(DEMO ? "Ticked on this page only: the demo saves nothing." : `Saved #${e.n}`);
    } catch (err) { say(err.message, true); }
  }
  apply.onchange = () => save({ apply: apply.checked });
  skip.onchange = () => save({ skip: skip.checked, skip_reason: reason.value });
  letter.onchange = () => save({ letter: letter.checked });
  let lastReason = reason.value;
  const saveReason = () => { if (reason.value !== lastReason) { lastReason = reason.value; save({ skip_reason: reason.value, ...(reason.value && !skip.checked ? { skip: (skip.checked = true) } : {}) }); } };
  reason.onblur = saveReason;
  reason.onkeydown = ev => { if (ev.key === "Enter") reason.blur(); };

  card.append(el("div", { class: "marks" },
    el("label", {}, apply, "apply"),
    el("label", {}, skip, "skip"),
    reason,
    el("label", {}, letter, "cover letter"),
  ));

  const chips = el("div", {});
  if (e.already_built) chips.append(el("span", { class: "chip ok" }, "resume filed"));
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

async function loadApplications() {
  const list = $("#app-list");
  list.replaceChildren();
  let apps;
  try { apps = await api("/api/applications"); } catch (e) { say(e.message, true); return; }
  const employers = apps.filter(a => a.employer), other = apps.filter(a => !a.employer);
  if (!apps.length) list.append(el("p", { class: "muted" }, "Nothing filed under Applications/ yet."));
  for (const a of employers) list.append(el("button", { class: "item", onclick: ev => openApplication(a, ev.currentTarget) }, a.company, el("small", {}, `${a.files.length} files`)));
  if (other.length) {
    list.append(el("h3", {}, "Not employers"));
    for (const a of other) list.append(el("button", { class: "item", onclick: ev => openApplication(a, ev.currentTarget) }, a.company.replace(/^_[^/]*\//, ""), el("small", {}, `${a.files.length} files`)));
  }
}

function openApplication(a, btn) {
  for (const b of document.querySelectorAll("#app-list .item")) b.classList.toggle("active", b === btn);
  const view = $("#app-view");
  const viewer = el("div");
  const files = el("ul", { class: "files" });
  for (const f of a.files) {
    const url = fileUrl(a.company, f.name);
    const link = f.viewable
      ? el("a", { href: "#", onclick: ev => { ev.preventDefault(); showFile(viewer, url, f.name); } }, f.name)
      : el("span", { class: "muted" }, f.name);
    files.append(el("li", {}, link, el("small", {}, `${f.modified} · ${fmtSize(f.size)}`)));
  }
  view.replaceChildren(el("h2", {}, a.company), files, viewer);
  const first = a.files.find(f => f.viewable && f.name.endsWith(".pdf")) || a.files.find(f => f.viewable);
  if (first) showFile(viewer, fileUrl(a.company, first.name), first.name);
}

// A filed document: from the server, or in a demo from the copies beside the page.
function fileUrl(company, name) {
  if (DEMO) return "files/" + [...company.split("/"), name].map(encodeURIComponent).join("/");
  return `/api/applications/${encodeURIComponent(company)}/${encodeURIComponent(name)}`;
}

async function showFile(viewer, url, name) {
  if (name.toLowerCase().endsWith(".pdf")) { viewer.replaceChildren(el("iframe", { class: "pdf", src: url })); return; }
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
  try { cmds = await api("/api/commands"); } catch (e) { say(e.message, true); return; }
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

  const old = await api("/api/runs");
  for (const r of old) attachRun(r, false);
  refreshSkillButtons();
}

function skillButton(s) {
  const btn = el("button", { class: "item skill", "data-skill": s.name }, s.label, el("small", {}, s.about + (s.needs === "date" ? " (the digest open in Digests)" : "")), routeLine(s.route));
  btn.route = s.route;
  btn.onclick = () => {
    if (s.needs !== "text") { startSkill(s.name, s.needs === "date" ? { date: currentDigest } : {}); return; }
    const box = el("textarea", { placeholder: "Paste the posting's URL, or the posting itself", rows: 4 });
    const go = el("button", { class: "action primary", onclick: () => { if (box.value.trim()) { startSkill(s.name, { text: box.value.trim() }); form.remove(); } } }, "Start");
    const form = el("div", { class: "skill-form" }, box, el("div", { class: "toolbar" }, go, el("button", { class: "action", onclick: () => form.remove() }, "Cancel")));
    btn.after(form);
    box.focus();
  };
  return btn;
}

function refreshSkillButtons() {
  for (const b of document.querySelectorAll("#run-commands .skill")) b.disabled = !!activeClaude;
  const banner = $("#run-active");
  if (activeClaude) {
    const text = `${activeClaude.name} is ${activeClaude.status}. One skill runs at a time.`;
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
        try { const run = await api("/api/claude/resume", { method: "POST", body: JSON.stringify({ session_id: p.session_id, text: box.value.trim(), ...activePick() }) }); form.remove(); attachRun(run, true); }
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
}

async function startRun(name, params, switchTab = false) {
  if (params && "date" in params && !params.date) { say("Open a digest first", true); return; }
  let run;
  try { run = await api("/api/runs/" + name, { method: "POST", body: JSON.stringify(params || {}) }); }
  catch (e) { say(e.message, true); return; }
  loaded.runs = true;
  attachRun(run, true);
  if (switchTab) showTab("runs");
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
  const es = new EventSource(`/api/runs/${run.id}/stream`);
  es.onmessage = ev => { pre.textContent += (pre.textContent ? "\n" : "") + ev.data; pre.scrollTop = pre.scrollHeight; };
  es.addEventListener("done", ev => { st.textContent = ev.data; st.className = "st " + ev.data; es.close(); if (loaded.digests && currentDigest) openDigest(currentDigest); });
  es.onerror = () => { es.close(); api("/api/runs/" + run.id).then(r => { pre.textContent = r.output.join("\n"); st.textContent = r.status; st.className = "st " + r.status; }); };
}

// ------------------------------------------------------- a skill's run

const ACTIVE = ["starting", "running", "waiting", "idle"];

async function attachClaudeRun(run, live) {
  const view = $("#run-view");
  if (view.firstElementChild && view.firstElementChild.classList.contains("muted")) view.replaceChildren();
  const st = el("span", { class: "st " + run.status }, run.status);
  const stop = el("button", { class: "action small" }, "Stop");
  const transcript = el("div", { class: "chat" });
  const cardArea = el("div");
  const reply = el("textarea", { class: "reply", rows: 2, placeholder: "Reply… (Enter sends, Shift+Enter for a new line)" });
  const send = el("button", { class: "action primary" }, "Send");
  const replyBox = el("div", { class: "replybox", hidden: "" }, reply, send);
  const when = new Date(run.started * 1000).toLocaleTimeString();
  const routed = run.route && run.route.label ? el("span", { class: "chip", title: run.route.why || "" }, run.route.label) : null;
  const panel = el("div", { class: "run claude", "data-run": run.id },
    el("div", { class: "head" }, el("b", {}, run.name), routed, el("span", { class: "muted" }, when), st, stop),
    transcript, cardArea, replyBox);
  view.prepend(panel);

  const state = { status: run.status, tools: {}, seen: 0 };
  const setStatus = s => {
    state.status = s; st.textContent = s; st.className = "st " + s;
    replyBox.hidden = s !== "idle";
    stop.textContent = s === "idle" ? "End run" : "Stop";
    stop.hidden = !ACTIVE.includes(s);
    const mine = ACTIVE.includes(s);
    if (mine) activeClaude = { id: run.id, name: run.name, status: s };
    else if (activeClaude && activeClaude.id === run.id) activeClaude = null;
    refreshSkillButtons();
    if (!mine) { if (loaded.digests) loadDigests(); if (loaded.applications) loadApplications(); setupState(); }
  };
  setStatus(run.status);

  stop.onclick = async () => { try { await api(`/api/claude/${run.id}/stop`, { method: "POST" }); } catch (e) { say(e.message, true); } };
  const doSend = async () => {
    const text = reply.value.trim(); if (!text) return;
    try { await api(`/api/claude/${run.id}/say`, { method: "POST", body: JSON.stringify({ text }) }); reply.value = ""; }
    catch (e) { say(e.message, true); }
  };
  send.onclick = doSend;
  reply.onkeydown = ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); doSend(); } };

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
      case "card": cardArea.replaceChildren(cardView(run.id, ev)); break;
      case "card_answered": cardArea.replaceChildren(); transcript.append(el("div", { class: "note" }, `${ev.decision === "deny" ? "Denied" : "Allowed"}`)); break;
      case "turn_end": setupState(); transcript.append(el("div", { class: "note" }, `turn ended · ${ev.num_turns ?? "?"} steps` + (ev.tokens ? ` · ${fmtTokens(ev.tokens)} tokens` : "") + (ev.cost ? ` · ≈$${ev.cost.toFixed(2)} so far at API prices` : ""))); break;
      case "error": transcript.append(el("div", { class: "bubble error" }, ev.message)); break;
    }
    transcript.scrollTop = transcript.scrollHeight;
  }

  try {
    const full = await api("/api/runs/" + run.id);
    for (const ev of full.output) render(ev);
    setStatus(full.status);
    if (!ACTIVE.includes(full.status)) return;
  } catch (e) { say(e.message, true); return; }

  const es = new EventSource(`/api/runs/${run.id}/stream?start=${state.seen}`);
  es.onmessage = ev => { try { render(JSON.parse(ev.data)); } catch (e) { /* a malformed line */ } };
  es.addEventListener("done", ev => { setStatus(ev.data); es.close(); });
  es.onerror = () => { es.close(); setTimeout(() => { panel.remove(); attachRun({ ...run, status: state.status }, true); }, 1500); };
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

async function loadSetup() {
  const view = $("#setup-view");
  const checking = () => el("div", {}, el("p", { class: "muted small" }, "Checking…"));
  const parts = { claude: checking(), files: checking(), problems: el("div"), scan: checking(), resume: checking() };
  const ready = el("div");
  const start = el("button", { class: "action primary", disabled: "", onclick: () => startSkill("setup", {}) }, "Set up");
  view.replaceChildren(
    el("div", { class: "toolbar" }, el("h2", {}, "Set up"), el("button", { class: "action small", onclick: () => loadSetup() }, "Check again")),
    DEMO ? el("p", { class: "banner" }, DEMO.setupNote) : "",
    ready,
    setupStep("1", "Claude Code", "The page runs your own Claude Code, with your own login, to do the interviewing, scoring and writing.", parts.claude),
    setupStep("2", "Your profile", "Set up interviews you and writes these files. Every write to your resume facts, stories or profile shows you the exact text first and waits for your approval.", el("div", {}, parts.files, parts.problems)),
    setupStep("3", "Before your first scan", "Two free job sources need a key. Each is saved to a gitignored file on this machine, never through Claude.", parts.scan),
    setupStep("4", "Before your first resume", "LaTeX typesets resumes and letters. Setup does not need it, so it can install while you go.", parts.resume),
  );

  let claude = null, state = null;
  const settle = () => {
    start.disabled = !(claude && claude.available);
    ready.replaceChildren(claude && claude.available && state && state.ready
      ? el("div", { class: "ready" }, el("b", {}, "You are set up. "), "Run a scan whenever you like; every skill is in the Runs tab.",
          el("div", { class: "toolbar" }, el("button", { class: "action primary", onclick: () => startSkill("job-scan", {}) }, "Job scan"), el("button", { class: "action", onclick: () => showTab("digests") }, "Digests")))
      : "");
  };
  api("/api/claude/status").catch(e => ({ available: false, reason: e.message }))
    .then(s => { claude = s; parts.claude.replaceChildren(...claudeView(s)); settle(); });
  const stated = setupState().then(s => { state = s; parts.files.replaceChildren(...(s ? filesView(s, start) : [el("p", { class: "muted" }, "Could not read how far setup has got.")])); settle(); });

  if (DEMO) { for (const k of ["scan", "resume"]) parts[k].replaceChildren(el("p", { class: "muted small" }, "Checked on your own copy.")); return; }
  let checks;
  try { checks = await api("/api/setup/checks"); }
  catch (e) { parts.scan.replaceChildren(el("p", { class: "muted" }, e.message)); parts.resume.replaceChildren(); return; }
  const rows = group => checks.checks.filter(r => r.group === group);
  parts.scan.replaceChildren(...checks.keys.map(keyForm), el("ul", { class: "checks" }, ...rows("sources").map(checkRow)));
  const latex = rows("latex");
  parts.resume.replaceChildren(el("ul", { class: "checks" }, ...latex.map(checkRow)),
    latex.some(r => r.status === "MISSING") ? el("p", { class: "muted small" }, "Run the install from a new terminal window. Once it is done, close the page's own window and start the page again: a page started before the install cannot find LaTeX.") : "");
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
    el("p", {}, el("span", { class: "chip bad" }, "not installed"), " Install it from a new terminal window, leaving the page's own window open, then press Check again. It needs a paid Claude plan or an Anthropic Console account."),
    command(s.install),
    el("p", { class: "muted small", html: 'Other ways to install it are in <a href="https://code.claude.com/docs/en/setup" target="_blank" rel="noopener">Claude Code\'s setup guide</a>.' })];
  if (s.login) return [
    el("p", {}, el("span", { class: "chip bad" }, "not logged in"), " Run this once in a new terminal window, leaving the page's own window open. It opens your browser to sign in; then press Check again."),
    command(s.login),
    el("p", { class: "muted small" }, "The Claude desktop app's own login does not carry over to it.")];
  return [el("p", {}, el("span", { class: "chip bad" }, "not available"), " " + (s.reason || ""))];
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

// ----------------------------------------------------------------- start

// A run started from another tab, or resumed from one, shows up here too,
// without a reload. attachRun() skips the ones already on the page.
setInterval(async () => {
  if (!loaded.runs || document.hidden) return;
  try { for (const r of await api("/api/runs")) attachRun(r, ACTIVE.includes(r.status)); }
  catch (e) { /* the server is restarting */ }
}, 4000);

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
  return Promise.reject(new Error(DEMO_NOTE));
}

// Tick a box in the bundled digest, and recount the way core.list_digests does.
function demoMark(date, n, marks) {
  const d = DEMO.get["/api/digests/" + date];
  const e = d.entries.find(x => x.n === n);
  for (const [k, field] of [["apply", "marked_apply"], ["skip", "marked_skip"], ["letter", "marked_letter"], ["skip_reason", "skip_reason"]]) {
    if (k in marks) e[field] = marks[k];
  }
  const a = x => x.marked_apply, s = x => x.marked_skip, l = x => x.marked_letter, es = d.entries;
  const counts = {
    date, entries: es.length,
    apply: es.filter(x => a(x) && !s(x)).length,
    skip: es.filter(x => s(x) && !a(x) && !l(x)).length,
    unmarked: es.filter(x => !a(x) && !s(x) && !l(x)).length,
    conflicts: es.filter(x => (s(x) && (a(x) || l(x))) || (l(x) && !a(x) && !s(x))).length,
  };
  Object.assign(DEMO.get["/api/digests"].find(x => x.date === date), counts);
  return counts;
}

if (DEMO && DEMO.banner) document.body.prepend(el("div", { class: "demo-banner", html: DEMO.banner }));

// The first tab: the one the address names, else Setup until the profile is
// written and reviewed, then Digests.
const TABS = ["setup", "digests", "applications", "runs", "profile"];
loadUsage();
setupState().then(s => {
  const asked = location.hash.slice(1);
  showTab(TABS.includes(asked) ? asked : s && !s.ready ? "setup" : "digests");
});
window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if (TABS.includes(t) && !$("#tab-" + t).classList.contains("active")) showTab(t); });
